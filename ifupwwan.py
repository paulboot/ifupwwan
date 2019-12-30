#!/usr/bin/python3


import logging
import queue
from pyroute2 import IPDB, IPRoute
import signal
import threading
import serial
from curses import ascii
from time import sleep
from pprint import pprint
from subprocess import PIPE, check_output 
import io

logpath='/var/log'
logfilename='ifupwwan'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(threadName)-10.10s] [%(levelname)-4.4s] %(message)s",
    datefmt='%m/%d/%Y %H:%M:%S',
    handlers=[
        logging.FileHandler("{0}/{1}.log".format(logpath, logfilename)),
        logging.StreamHandler()
    ])

log = logging.getLogger(__name__)
log.info('Start logging')

work_queue = queue.Queue()
ip = IPDB()
# get access to the netlink socket
ipr = IPRoute()

def out(command):
    result = check_output(command, universal_newlines=True, shell=True)
    for line in result.splitlines():
        log.info(line)
    return result

def connect():
    log.info('Going to connect LTE modem on ttyUSB0')
    ser = serial.Serial('/dev/ttyUSB0', 460800, timeout=1)
    sio = io.TextIOWrapper(io.BufferedRWPair(ser, ser), encoding='ascii')

    sio.write('AT^NDISDUP=1,1,\r\n')
    sio.flush()
    sleep(.1)
    for line in sio:
        log.info('After AT connect looking for OK')
        line=line[:-1]
        log.info(line)
        if line == "OK":
            log.info('Found OK going to break for loop')
            break
        sleep(.1)

    out('/sbin/dhclient -v -r wwan0 2>&1')
    out('/sbin/dhclient -v wwan0 2>&1')
    out('/sbin/ip link 2>&1 | /bin/grep wwan')
    ser.close()

class Worker(threading.Thread):
    def run(self):
        while True:
            msg = work_queue.get()
            log.debug(msg['event'])
            if msg['event'] == 'RTM_NEWLINK':
                ifname = msg['attrs'][0][1]
                operstate = msg['attrs'][2][1]
                log.debug(ifname + 'is ifname')
                log.debug(operstate + ' is state')
                if ifname == 'wwan0' and operstate == 'DOWN':
                    log.info('State wwan0 is DOWN event ' + msg['event'] + ' going to reconnect')
                    connect()
                elif ifname == 'wwan0':
                    log.info('State wwan0 is ' + operstate + ' not DOWN ignoring event ' + msg['event'])
                else:
                    log.info('Ignoring event for interface ' + ifname + ' not wwan0')


# POSIX signal handler to ensure we shutdown cleanly
def handler(signum, frame):
    log.info('Caught shutdown, down IPDB and IPRoute instance...')
    ip.release()
    ipr.close()

# Called by the IPDB Netlink listener thread for _every_ message (route, neigh, etc,...)
def callback(ipdb, msg, action):
    if action != 'RTM_NEWNEIGH':
        work_queue.put(msg)

def main():
    log.info('Start main')
   
    out('/sbin/ip link 2>&1 | /bin/grep wwan')
 
    logging.basicConfig(level=logging.DEBUG)

    # Register our handler for keyboard interrupt and termination signals
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    
    # Worker thread
    worker = Worker()
    worker.daemon = True
    worker.start()
    
    # Register our callback to the IPDB
    ip.register_callback(callback)

    log.info('Checking initial state of wwan0')
    operstate=ipr.get_links(ipr.link_lookup(ifname='wwan0'))[0].get_attr('IFLA_OPERSTATE')
    if operstate == 'DOWN':
        connect()
    elif operstate == 'UP':
        log.info('Interface is UP doing nothing waiting....')

    # The process main thread does nothing but waiting for signals
    signal.pause()
    log.info('End main')

main()

