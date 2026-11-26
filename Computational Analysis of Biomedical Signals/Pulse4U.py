"""Pulse4U Graphical User Interface (GUI) - BMET 2922 Major Project

This program is responsible for the GUI display and works in conjuction with the Arduino implementation file

Authors:
Kylie, Carlos, Pranjali
""" 


#Importing Required Libraries
import PySimpleGUI as sg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg #canvas element
import numpy as np
import sys
import matplotlib.animation as animation
import serial
from datetime import datetime 
import time

data_reception_timeout = 5 #variable for the data timeout alert
last_data_received= time.time()

#Chosing the theme and hex code colour (pink)
sg.theme('DarkGreen')
sg.theme_background_color('#f85c84')

#Creating lists to store package number, bpm and raw pulse
PACKAGE_NUMBERList= [] #package number
HR_BPMList = [] #bpm list
RAW_PULSEList = [] # pulse data from values between first and last
RAW_PUlSE_packet_window= [] #data for the packet window
SYSTEM_LOG_WINDOW_MESSAGES_List= [] #logs the system messages for window display


#Creating function for animated graph high/low alerts. Argument i indicates the most recent frame parameter
def animate(i): 
    global PACKAGE_NUMBERList, HR_BPMList, RAW_PULSEList, RAW_PUlSE_packet_window, last_data_received #parameter = package number list, bpm list, raw pulse data list, data list for raw data packet window, time where last data received
    try:
        ardData_string = ser.readline().decode('ascii') 
        ardData_vals = ardData_string.strip().split(',')
        if len(ardData_vals) >= 1: 
            ard_package_num = ardData_vals[0]
            PACKAGE_NUMBERList.append(ard_package_num)
            ard_data_float = float(ardData_vals[-1])
            HR_BPMList.append(ard_data_float) 
            raw_pulse_data = [int(x) for x in ardData_vals[1:-1]]
            RAW_PUlSE_packet_window = raw_pulse_data 
            bpm = int(ardData_vals[-2]) 
            update_subplots(HR_BPMList, raw_pulse_data, RAW_PULSEList, bpm)       
        else:
            print("Invalid data format")

        #Establishing a threshold for high or low pulse alert
        high_pulse_alert = ard_data_float > 135 
        low_pulse_alert = ard_data_float < 40 
        
        #Writing alert messages for high or low pulse
        if high_pulse_alert: 
            window['-HIGH-ALERT-'].update("{} \nALERT! Pulse is too high. Check Pulse4U Program!".format(datetime.now().ctime()), background_color='white')
            high_alert_message = "{}: High Pulse!".format(datetime.now().ctime())
            SYSTEM_LOG_WINDOW_MESSAGES_List.append(high_alert_message)
            window['-LOG-SYSTEM-WINDOW-'].update('\n'.join(SYSTEM_LOG_WINDOW_MESSAGES_List))
        else: #clear the message and revert back to the background color
            window['-HIGH-ALERT-'].update("", background_color='#f85c84')
        if low_pulse_alert:
            window['-LOW-ALERT-'].update("{} \nALERT! Pulse is too low. Check Pulse4U Program!".format(datetime.now().ctime()), background_color='white')
            low_alert_message = "{}: Low Pulse!".format(datetime.now().ctime())
            SYSTEM_LOG_WINDOW_MESSAGES_List.append(low_alert_message)
            window['-LOG-SYSTEM-WINDOW-'].update('\n'.join(SYSTEM_LOG_WINDOW_MESSAGES_List))
        else:#clears the low alert message and reverts back to the chosen pink hex color background
            window['-LOW-ALERT-'].update("", background_color='#f85c84') 
        # Displaying the most recent heart rate data clearly on the screen
        window['-HEART-RATE-'].update(f'Heart Rate: {ard_data_float:.1f} bpm')
        window['-TIME-ALERT-'].update("", background_color='#f85c84') #clears time alarm, reverts back to pink background color if the time alert is not activated
       
    except Exception as e: 
        print("Error reading Arduino data:", e)
        if time.time() - last_data_received > data_reception_timeout:#calculates whethere the latest package was received longer than 5 seconds ago, then triggering the alert
            window['-TIME-ALERT-'].update("{}\nNo data packages received in the last 5 seconds!".format(datetime.now().ctime()), background_color='white')
            time_alert_message = "{}: No data packages received in the last 5 seconds!".format(datetime.now().ctime())
            SYSTEM_LOG_WINDOW_MESSAGES_List.append(time_alert_message)
            window['-LOG-SYSTEM-WINDOW-'].update('\n'.join(SYSTEM_LOG_WINDOW_MESSAGES_List))
        else:
            window['-TIME-ALERT-'].update("", background_color='#f85c84') 
        

    #Changing fonts in Matplotlib using font family
    plt.rcParams['font.size'] = 11
    plt.rcParams['font.family'] = 'serif'
    plt.rcParams['font.style'] = 'normal'
    
    #Defining the variables and components of the graphs
    HR_BPMList = HR_BPMList[-50:]
    RAW_PULSEList = RAW_PULSEList[-50:]
    bpm_graph.clear()
    bpm_graph.plot(HR_BPMList, color='red')
    bpm_graph.set_ylim([0, 140])
    bpm_graph.set_title("Heart Rate BPM Data")
    bpm_graph.set_ylabel("Heart Rate (bpm)")
    bpm_graph.set_xlabel("Time (sec)")

    raw_data_graph.clear()
    raw_data_graph.plot(np.linspace(0,1, num=50), RAW_PULSEList, color='blue')
    raw_data_graph.set_ylim([0, 4100])
    raw_data_graph.set_title("\n\nRaw Pulse Data")
    raw_data_graph.set_ylabel("Amplitude")
    raw_data_graph.set_xlabel("Time (sec)")

    #Calculating the average HR values
    if HR_BPMList:
        moving_average = np.mean(HR_BPMList) 
        min_hr = min(HR_BPMList)
        max_hr = max(HR_BPMList)
    else:
        moving_average = min_hr = max_hr = 0

    #Displaying the current HR values and the min and max
    window['-AVG-HR-'].update(f'{moving_average:.1f}')  
    window['-MIN-HR-'].update(f'{min_hr}')
    window['-MAX-HR-'].update(f'{max_hr}')  

    #Drawing the graph
    canvas.draw()

#Function to continously update the graphs with latest data received
def update_subplots(dataList, raw_pulse_data, bpmList, bpm): # arguments: continuously updated lists of accumulated BPM data & raw pulse data, bpm list, recent bpm
    global last_data_received, RAW_PULSEList
    last_data_received = time.time()
    HR_BPMList = dataList[-50:]
    RAW_PULSEList.extend(raw_pulse_data)  
    RAW_PULSEList = RAW_PULSEList[-50:]  
    # Heart Rate BPM subplot
    bpm_graph.clear()
    bpm_graph.plot(HR_BPMList, color='red')
    bpm_graph.set_ylim([0, 140])  # Min to max heart rate
    bpm_graph.set_title("Heart Rate BPM Data")
    bpm_graph.set_ylabel("Heart Rate (bpm)")
    bpm_graph.set_xlabel("Time (sec)")

    # Raw pulse data subplot
    raw_data_graph.clear()
    raw_data_graph.plot(np.linspace(0,1,num=50), RAW_PULSEList, color='blue')
    raw_data_graph.set_ylim([0, 4100])
    raw_data_graph.set_title("Raw Pulse Data")
    raw_data_graph.set_ylabel("Amplitude")
    raw_data_graph.set_xlabel("Time (sec)")
    plt.tight_layout()


#Enabling the code to be executed when using it as a script
if __name__ == '__main__': #main figure window display
    fig, (bpm_graph, raw_data_graph) = plt.subplots(2, 1, gridspec_kw={'height_ratios': [2, 1]}) #ratio for bpm to pulse
    canvas_elem = sg.Canvas(size=(1200, 700), key='-CANVAS-') #old canvas elem, size updated later on
    main_font = ('8514oem', 14)
    alert_font = ('8514oem', 19)

#Layout of window (canvas, buttons, high alert & low alert layout displays, placement of min, max and avg HR)
    layout = [
        [
            sg.Column([ 
                [canvas_elem],
                [sg.Button('Package Data', font=main_font)], 
                [sg.Button('Reset', font=main_font)],
                [sg.Button('Exit', font=main_font)],
                [sg.Text('Save n Capture Exit- Select Graph Type:', font=main_font),sg.Combo(['Weekly Data', 'Monthly Data'], key='-GRAPH-TYPE-', font=main_font)],
                [sg.Button('Display Graph', font=main_font)],
            ]),
            sg.Column([ #data to the right of the graph
                [sg.Text('Hello, and welcome to Pulse4U. Please press the button on your device to read or stop reading data.', font=main_font)],
                [sg.Text('Average HR: ', justification='right', font=main_font), sg.Text(size=(10, 1), key='-AVG-HR-', justification='left', font=main_font)],
                [sg.Text('Min HR: ', justification='right', font=main_font), sg.Text(size=(10, 1), key='-MIN-HR-', justification='left', font=main_font)],
                [sg.Text('Max HR: ', justification='right', font=main_font), sg.Text(size=(10, 1), key='-MAX-HR-', justification='left', font=main_font)],
                [sg.Text('', size=(56, 2), key='-TIME-ALERT-', justification='left', text_color='red', background_color='#f85c84', font=alert_font)],
                [sg.Text('', size=(56, 2), key='-HIGH-ALERT-', justification='left', text_color='red', background_color='#f85c84', font=alert_font)],
                [sg.Text('', size=(56, 2), key='-LOW-ALERT-', justification='left', text_color='red', font=alert_font, background_color='#f85c84')],
                [sg.Text('', size=(56, 1), key='-HEART-RATE-', justification='left', font=alert_font)],
                [sg.Text('System Log Window', font=main_font, background_color='white')],
                [sg.Multiline('{}: Welcome'.format(datetime.now().ctime()), size=(56, 6), key='-LOG-SYSTEM-WINDOW-', justification='left', font=main_font, background_color='white', autoscroll=True)]
            ])
        ]
    ]

    window = sg.Window('Pulse4U', layout, finalize=True, size=(1850, 850))
    canvas = FigureCanvasTkAgg(fig, master=canvas_elem.Widget) 
    canvas.get_tk_widget().pack(side='top', fill='both', expand=1)
    canvas.draw()

    #Setting the COM port name here
    portName = "COM5"

    #Defining serial port at 115200 bauds
    serialPort = serial.Serial()
    serialPort.port = portName
    serialPort.baudrate = 115200
    serialPort.bytesize = 8
    serialPort.timeout = 2
    serialPort.stopbits = serial.STOPBITS_ONE

    #Opening the serial port
    try:
        serialPort.open()
    except:
        print("Port open failed: " + portName)
        for e in sys.exc_info():
            print("  ", e)

    if serialPort.isOpen():
        #Assigning serial port
        ser = serialPort 
        print("**************************************")
        print("** Serial port opened: {}".format(portName))
        print("**************************************")
        #Initialising the animation
        ani = animation.FuncAnimation(fig, animate, interval=100) #frame #update
        packet_info = ""
        #Reading the user interactions with GUI and interprets the pressing of the button
        while True:
            event, values = window.read()
            #Closing the window when the exit button is pressed or the window is closed           
            if event == sg.WIN_CLOSED or event == 'Exit':
                break
            #Reseting the graph when the reset button is pressed
            if event == 'Reset':
                HR_BPMList = []
                RAW_PULSEList = []
                raw_data_graph.clear()
                raw_data_graph.set_ylim([0, 140])
                raw_data_graph.set_title("Heart Rate BPM Data")
                raw_data_graph.set_ylabel("Heart Rate (bpm)")
                raw_data_graph.set_xlabel("Time (sec)")
                bpm_graph.clear()
                bpm_graph.set_ylim([0, 4100])
                bpm_graph.set_title("Raw Pulse Data")
                bpm_graph.set_ylabel("Amplitude")
                bpm_graph.set_xlabel("Time (sec)")
                window['-AVG-HR-'].update("0.00")
                window['-MIN-HR-'].update("0")
                window['-MAX-HR-'].update("0")
                window['-HIGH-ALERT-'].update("", background_color='#f85c84')
                window['-LOW-ALERT-'].update("")
                window['-HEART-RATE-'].update('')
                window['-LOG-SYSTEM-WINDOW-'].update("")
                SYSTEM_LOG_WINDOW_MESSAGES_List = []
                plt.tight_layout() #adjusts the layout to fit the words
            #Opening the system log window to display the latest package data
            if event == 'Package Data':
                sg.popup("Most Recent Package Information:\n{}\nPackage number: {}\nHeart Rate (bpm): {}\nRaw Data: {}".format(datetime.now().ctime(),PACKAGE_NUMBERList[-1],HR_BPMList[-1], RAW_PUlSE_packet_window[-50:])) #package number list, hr bpm list, and the packet info in window
            # Displaying the graph based on the selected graph type, hard-coded because don't have weekly/monthly data
            if event == 'Display Graph': 
                selected_graph_type = values['-GRAPH-TYPE-']
                if selected_graph_type == 'Weekly Data':#Makes graphical display for the weekly data, make sure to press "Display Graph" button for it to work
                    x = [1, 2, 3, 4, 5, 6, 7]
                    y = [89, 93, 92, 88, 100, 99, 87]
                    plt.figure()
                    plt.plot(x, y, marker='o', color='red')
                    plt.title('Weekly Heart Rate Data')
                    plt.xlabel('Day')
                    plt.ylabel('Heart Rate (bpm)')
                    plt.grid()
                    plt.show()      
                elif selected_graph_type == 'Monthly Data': #Makes graphical display for the monthly data, make sure to press "Display Graph" button for it to work
                    x = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
                    y = [89, 93, 92, 88, 100, 99, 87, 93, 94, 94, 96, 82, 88, 87, 90, 78, 90, 91, 96, 96, 96, 89, 90, 97, 92, 81, 92, 94, 87, 94]
                    plt.figure()
                    plt.plot(x, y, marker='o', color='red')
                    plt.title('Monthly Heart Rate Data')
                    plt.xlabel('Day')
                    plt.ylabel('Heart Rate (bpm)')
                    plt.grid()
                    plt.show()                
    else:
        print("Exiting")
