#!/usr/bin/env python3

import logging
import os
import shutil
import socket
import struct
import subprocess
import time

if os.getenv('DEBUG'):
    logging.basicConfig(level=logging.DEBUG)
    logging.debug("Debugging log level is enabled")
else:
    logging.basicConfig(level=logging.INFO)


def try_kill_process(process):
    try:
        process.kill()
    except Exception as e:
        logging.info("Could not kill process %s: %s" % (str(process), str(e)))


start_delay = int(os.getenv('START_DELAY', 10))
sync_folder = os.getenv('SYNC_FOLDER', '/data')
sync_group = os.getenv('SYNC_GROUP', 'data-sync')
sync_interval = int(os.getenv('SYNC_INTERVAL', 0))  # Max. interval in seconds
sync_timeout = int(os.getenv('SYNC_TIMEOUT', 0))
if sync_timeout <= 0:
    sync_timeout = None
sync_types = ['next', 'first', 'all']
sync_type = os.getenv('SYNC_TYPE', sync_types[0]).lower()  # Sync type for distributed sync
if sync_type not in sync_types:
    logging.info("%s is no valid sync type. Set to default %s" % (sync_type, sync_type[0]))
    sync_type = sync_types[0]

shutil.rmtree('/root/.unison', ignore_errors=True)  # Cleanup

args = ["unison", "-socket", "2222"]
server_process = subprocess.Popen(args)
try:
    logging.debug("Sync server started with args: %s" % args)
    time.sleep(start_delay)  # Wait before servers are ready

    last_sync = 0
    while True:
        # Shutdown if sync server has stopped
        if server_process.poll() is not None:
            logging.warn("Sync server is not running anymore. Shutting down!")
            break

        if (time.time() - last_sync > sync_interval):
            logging.debug("Now syncing")
            last_sync = time.time()

            # Get the ips of all replicas without that of this container
            group_ips = socket.gethostbyname_ex(sync_group + ".")[2]
            # Sort ips from 0.0.0.0 to 255.255.255.255 by each byte value
            group_ips = sorted(group_ips, key=lambda ip: struct.unpack("!L", socket.inet_aton(ip))[0])
            logging.debug("Group ips are %s" % group_ips)

            container_ip = socket.gethostbyname_ex(socket.gethostname() + ".")[2][0]
            logging.debug("Container ip is %s" % container_ip)
            if container_ip not in group_ips:
                logging.error("IP of Container %s is not part of group %s. "
                              "Have you connected all hosts via the network?" % (container_ip, group_ips))

            # Create list of sync targets
            sync_ips = []
            if sync_type == "first":
                sync_ips = [group_ips[0]]
            elif sync_type == "next":
                container_ip_pos = group_ips.index(container_ip)
                next_index = (container_ip_pos + 1) % len(group_ips)
                sync_ips = [group_ips[next_index]]
            elif sync_type == "all":
                sync_ips = group_ips

            # Container should not sync to itself
            if container_ip in sync_ips:
                sync_ips.remove(container_ip)

            # If there is no sync partner then cancel
            if not sync_ips:
                logging.info("No ips to sync.")

            for sync_ip in sync_ips:
                sync_source = sync_folder
                sync_target = "socket://%s:%s/%s" % (sync_ip, 2222, sync_source)
                # Ignore .tmp files
                args = ["unison", "-auto", "-batch", "-fastcheck",
                        "-group", "-owner", "-prefer=newer", "-silent",
                        "-times", "-confirmbigdel=false", "-confirmmerge=false",
                        "-ignore", "Name *.tmp", sync_source, sync_target]
                logging.info("Running sync (Timeout: %s) with args: %s " % (sync_timeout, args))
                sync_process = subprocess.Popen(args)
                returncode = sync_process.wait(timeout=sync_timeout)
                logging.debug("Sync process stopped with exit code %s" % returncode)
                if returncode is None:
                    logging.warn("Could not finish sync in timeout %s" % sync_timeout)
                    try_kill_process(sync_process)

        next_sync = sync_interval - (time.time() - last_sync)
        if next_sync > 0:
            logging.debug("Next sync in %ss" % next_sync)
            time.sleep(next_sync)
finally:
    # Shutdown server
    try_kill_process(server_process)
