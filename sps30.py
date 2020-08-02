"""
Binh Nguyen, June 14, 2020
- A fork from Szymon Jakubiak (2018)
- additional feature:
 1. push data to MQTT server 
 2. log file to CSV format (both of them are optional)
 3. run multiple SPS30 with USB hub (quality check SPS30 sensors)
"""

import serial, struct, time
import subprocess
from operator import invert
import os
import json
import socket
import paho.mqtt.publish as publish

# set localtime
os.environ['TZ'] = 'Asia/Ho_Chi_Minh'
time.tzset()

# MQTT host, users
mqtt = '192.168.1.100'  # change this
topic = 'sensor/sps30' # and this
auth = {'username': 'mqtt_user', 'password': 'mqtt_password'} # and these two


def get_usb():
    '''
    - list all devices connected to USB port
    -  make sure no other devices rather SDS011 sensors connected
    '''


    try:
        with subprocess.Popen(['ls /dev/ttyUSB*'], shell=True, stdout=subprocess.PIPE) as f:
            usbs = f.stdout.read().decode('utf-8')
        usbs = usbs.split('\n')
        usbs = [usb for usb in usbs if len(usb) > 3]
    except Exception as e:
        print('No USB available')
    return usbs

def time_(): return int(time.time())


def datetime_():
    return time.strftime('%x %X', time.localtime())


def host_folder():
    """designate a folder to save data"""
    this_month_folder = time.strftime('%b%Y')
    basedir = os.path.abspath(os.path.dirname(__file__))
    # basedir = '/'.join(basedir.split('/')[: -1]) #  make one level up
    all_dirs = [d for d in os.listdir(basedir) if os.path.isdir(d)]
    if len(all_dirs) == 0 or this_month_folder not in all_dirs:
        os.makedirs(this_month_folder)
        print('created: {}'.format(this_month_folder))
    return os.path.join(basedir, this_month_folder)


def internet_ready():
    '''check if internet connection is ready'''

    try:
        _ = socket.create_connection((mqtt, 1883), 3)
        return True
    except Exception as e:
        print("Error {}".format(e))
        return False


def record_data(data):
    '''save data to CSV file'''
    id_  = data.split(',')[0]
    id_ = f'{id_}'
    filename = os.path.join(host_folder(), f'{id_}.csv')
    with open(filename, 'a+') as f:
        f.write(f'{data}\n')
        print(data)
    return None


def push_mqtt_server(data):
    '''push data to MQTT server'''
    
    header = ['sensor','time','PM1','PM25','PM4','PM10','b0305',
            'b031','b0325','b034','b0310','tsize']
    data = data.split(',')
    if len(header) == len(data):
        print(f'Process for MQTT {data}')    
        payload = dict(zip(header,data))
        payload['type'] = 'json'
        print(f'MQTT: {payload}')
        payload = json.dumps(payload)
        try:
            if internet_ready():
                publish.single(topic, payload, hostname=mqtt, auth=auth)

        except Exception as e:
            print('Error: {}'.format(e))
            pass
    return None



class SPS30:
    NAME = 'SPS30'
    WARMUP = 20 # seconds
    
    def __init__(self, port, save_data=True, push_mqtt=False, INTERVAL=60):
        self.port = port
        self.interval = INTERVAL
        self.warmup = SPS30.WARMUP
        self.save_data = save_data
        self.push_mqtt = push_mqtt
        self.name = SPS30.NAME
        self.lastSample = 0
        self.fanOn = 0
        self.is_started = False
        self.ser = serial.Serial(self.port, baudrate=115200, stopbits=1, parity="N",  timeout=2)

    def __str__(self):
        return f'{self.port}, {self.name}, {self.fanOn}, {self.lastSample}'

    
    def start(self):
        self.ser.write([0x7E, 0x00, 0x00, 0x02, 0x01, 0x03, 0xF9, 0x7E])
        
    def stop(self):
        self.ser.write([0x7E, 0x00, 0x01, 0x00, 0xFE, 0x7E])
    
    def read_values(self):
        self.ser.flushInput()
        # Ask for data
        self.ser.write([0x7E, 0x00, 0x03, 0x00, 0xFC, 0x7E])
        toRead = self.ser.inWaiting()
        # Wait for full response
        # (may be changed for looking for the stop byte 0x7E)
        while toRead < 47:

            toRead = self.ser.inWaiting()
            print(f'Wait: {toRead}')
            time.sleep(1)
        raw = self.ser.read(toRead)
        
        # Reverse byte-stuffing
        if b'\x7D\x5E' in raw:
            raw = raw.replace(b'\x7D\x5E', b'\x7E')
        if b'\x7D\x5D' in raw:
            raw = raw.replace(b'\x7D\x5D', b'\x7D')
        if b'\x7D\x31' in raw:
            raw = raw.replace(b'\x7D\x31', b'\x11')
        if b'\x7D\x33' in raw:
            raw = raw.replace(b'\x7D\x33', b'\x13')
        
        # Discard header and tail
        rawData = raw[5:-2]
        
        try:
            data = struct.unpack(">ffffffffff", rawData)
        except struct.error:
            data = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return data
    
    def read_serial_number(self):
        self.ser.flushInput()
        self.ser.write([0x7E, 0x00, 0xD0, 0x01, 0x03, 0x2B, 0x7E])
        toRead = self.ser.inWaiting()
        while toRead < 7:  #24
            toRead = self.ser.inWaiting()
            print(f'Wait: {toRead}')
            time.sleep(1)
        raw = self.ser.read(toRead)
        
        # Reverse byte-stuffing
        if b'\x7D\x5E' in raw:
            raw = raw.replace(b'\x7D\x5E', b'\x7E')
        if b'\x7D\x5D' in raw:
            raw = raw.replace(b'\x7D\x5D', b'\x7D')
        if b'\x7D\x31' in raw:
            raw = raw.replace(b'\x7D\x31', b'\x11')
        if b'\x7D\x33' in raw:
            raw = raw.replace(b'\x7D\x33', b'\x13')
        
        # Discard header, tail and decode
        serial_number = raw[5:-3].decode('ascii')
        return serial_number

    def run_query(self):
        if time_() - self.lastSample >= self.interval:
            if not self.is_started:   
                self.start()
                self.fanOn = time_()
                self.is_started = True
            if self.name == SPS30.NAME:
                name_  = self.read_serial_number()
                if len(name_) >0:
                    self.name = f'SPS_{name_}'
            if time_() - self.fanOn >= self.warmup:
                output = self.read_values()
                sensorData = ""
                for val in output:
                    sensorData += "{0:.2f},".format(val)

                output = ','.join([self.name, datetime_(),sensorData[:-1]])
                self.lastSample = time_()
                if self.is_started:
                    self.stop()
                    self.is_started = False
                if self.save_data:
                    record_data(output)
                if self.push_mqtt:
                    push_mqtt_server(output)
            else:
                time.sleep(1)
        return None

    def close_port(self):
        self.ser.close()


if __name__ == '__main__':
    # s1 = SPS30(port='/dev/ttyUSB0', push_mqtt=True)
    usbs = get_usb()
    print(usbs)
    process = list()
    for port in usbs:
        p = SPS30(port=port, push_mqtt=False)
        process.append(p)
    print('Starting')
    while True:
        for p in process:
            p.run_query()
