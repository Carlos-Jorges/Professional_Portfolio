import serial 
import time
import sys 
#serialString = ""

portName = "/dev/cu.ESP32Pranjali4"
#portName = "COM7"
serialPort = serial.Serial()
serialPort.port=portName 
serialPort.baudrate=115200
serialPort.bytesize=8
serialPort.parity = 'N' # no Parity
serialPort.timeout=0.1 
serialPort.stopbits=serial.STOPBITS_ONE
 

# open the port
try:
    serialPort.open()
except:
    print("Port open failed: " + portName)
    for e in sys.exc_info():
        print("  ",e)
    

if serialPort.isOpen():
    print("**************************************")
    print("** Serial port opened: {}".format(portName))
    print("**************************************")

    while 1:
        alert = input('Type something:')
        serialPort.write(alert)
        time.sleep(0.05)
    
        
else:
    print("Exiting")

