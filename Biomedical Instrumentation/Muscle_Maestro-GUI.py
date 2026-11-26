"BMET3802 Biomedical Instrumentation - Electromyograph (EMG) Final Project"
"Muscle Maestro - EMG Device"

"Ciya Shajan"
"Carlos Jorges"
"Jorge Bohr"
"Hannah Carr"

# Importing required libraries
import PySimpleGUI as sg
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import time
import serial
import csv  # Import the CSV module
from datetime import datetime  # Import datetime for unique filenames


# Set up the serial connection (adjust 'COM_PORT' and 'BAUD_RATE' as needed)
COM_PORT = 'COM5'  # Change this to your Arduino's port
BAUD_RATE = 9600  # Change this to your Arduino's baud rate
arduino = serial.Serial(COM_PORT, BAUD_RATE, timeout=1)

# Function to create the initial plot
def plot_init(title):
    fig, ax = plt.subplots(figsize=(12, 7))  # Create a figure and axis for the plot
    lines, = ax.plot([], [], lw=2)  # Initialize an empty line for the plot
    ax.set_xlim(0, 10)  # Set initial x-axis limits for 10 seconds
    ax.set_ylim(0, 5)  # Change y-axis limits to 0 to 5
    ax.grid(True)  # Enable the grid on the plot
    ax.set_title(title, fontsize=20)  # Set the title of the plot with increased font size
    ax.set_ylabel("Amplitude (V)", fontsize=15)  # Label for the y-axis with increased font size
    ax.set_xlabel("Time (s)", fontsize=15)  # Label for the x-axis with increased font size
    return fig, ax, lines  # Return the figure, axis, and line objects

# Function to draw the figure on the PySimpleGUI Canvas
def draw_figure(canvas, figure):
    figure_canvas_agg = FigureCanvasTkAgg(figure, canvas)  # Create a Tkinter canvas from the matplotlib figure
    figure_canvas_agg.draw()  # Draw the initial plot onto the canvas
    figure_canvas_agg.get_tk_widget().pack(side='top', fill='both', expand=1)  # Pack the canvas widget into the window
    return figure_canvas_agg  # Return the figure-canvas object for further manipulation

# Function for dynamic plotting and GUI event loop handling
def dynamic_plot(window, canvas_elem):
    buffer_time = []  # List to store time values for the x-axis
    buffer_amplitude = []  # List to store amplitude values for the y-axis

    is_paused = False  # Flag to check if the plot is paused

    # Initialize the plot and get the figure, axis, and line objects
    fig, ax, lines = plot_init("Real-Time EMG Signal")
    figure_canvas_agg = draw_figure(canvas_elem.TKCanvas, fig)
    start_time = time.perf_counter()  # Get the start time
    update_time = 1.0  # Time interval for updating the plot (1 second)
    next_update = start_time + update_time  # Initialize the next update time

    old_zoom_factor = 1

    csv_filename= f'emg_data.csv'

    # Open a CSV file for writing
    with open(csv_filename, mode='w', newline='') as csv_file:
        csv_writer = csv.writer(csv_file)  # Create a CSV writer
        csv_writer.writerow(['Time (s)', 'Amplitude (V)'])  # Write header

        while True:
            event, values = window.read(timeout=50)  # Read the window events
            # Get zoom factor from the slider
            zoom_factor = values['-ZOOM-']
            # Handle events
            if event in (sg.WIN_CLOSED, 'Exit'):
                break
            elif event == 'Pause':
                is_paused = True
            elif event == 'Play':
                is_paused = False
            elif event == 'Down':
                ax.set_ylim(ax.get_ylim()[0] + 1 / zoom_factor, ax.get_ylim()[-1] + 1 / zoom_factor)
            elif event == 'Up':
                ax.set_ylim(ax.get_ylim()[0] - 1 / zoom_factor, ax.get_ylim()[-1] - 1 / zoom_factor)

            # Set new y-axis limits based on zoom factor
            center_v = (ax.get_ylim()[-1] + ax.get_ylim()[0]) / 2
            y_range = 5 / zoom_factor 
            if zoom_factor != old_zoom_factor:
                ax.set_ylim(center_v - y_range / 2, center_v + y_range / 2)
                old_zoom_factor = zoom_factor
            else:    
                pass

            # Read data from the serial port
                try:
                    line = arduino.readline().decode().strip()
                    if line:
                        data_parts = line.split(',')
                        if len(data_parts) >= 1:
                            amplitude = float(data_parts[0])
                            # Collect time based on elapsed time
                            elapsed_time = time.perf_counter() - start_time
                            # Append data to buffers
                            buffer_time.append(elapsed_time)
                            buffer_amplitude.append(amplitude)

                            for t, a in zip(buffer_time, buffer_amplitude):
                                csv_writer.writerow([t, a])  # Write time and amplitude to CSV

                            # Keep only the last 10 seconds of data
                            while buffer_time and buffer_time[0] < elapsed_time - 10:
                                buffer_time.pop(0)  # Remove the oldest time value
                                buffer_amplitude.pop(0)  # Remove the oldest amplitude value
                            # Check if it's time to update the plot
                            if time.perf_counter() >= next_update:
                                # Update the plot data
                                lines.set_xdata(buffer_time)
                                lines.set_ydata(buffer_amplitude)
                                # Update x-axis limits to scroll
                                ax.set_xlim(max(0, elapsed_time - 10), elapsed_time)
                                # Redraw the figure on the canvas
                                if not is_paused:
                                    figure_canvas_agg.draw()
                                
                                # Write the current buffer to the CSV file
                                # for t, a in zip(buffer_time, buffer_amplitude):
                                #     csv_writer.writerow([t, a])  # Write time and amplitude to CSV

                                # Set the next update time
                                next_update += update_time
                except Exception as e:
                    print(f"Error reading from serial port: {e}")
                    continue
        
    plt.close(fig)  # Close the matplotlib figure to release resources

# Set GUI colour theme
sg.theme('DarkBlue12')
# Get the screen resolution
screen_width, screen_height = sg.Window.get_screen_size()

# Define the PySimpleGUI layout
layout = [
    [sg.Text('Group 7A EMG Sensor Device', font=("Helvetica", 25, 'bold'), justification='center', expand_x=True)],
    [sg.Canvas(size=(screen_width, screen_height), key='-CANVAS-')],
    [sg.Text('Zoom:', font=("Helvetica", 15)), sg.Slider(range=(1, 20), default_value=1, orientation='h', size=(40, 15), key='-ZOOM-')],
    [sg.Button('Play', size=(15, 5), font=("Helvetica", 15)),
     sg.Button('Pause', size=(15, 5), font=("Helvetica", 15)),
     sg.Button('Exit', size=(15, 5), font=("Helvetica", 15)),
     sg.Button('Up', size=(15, 5), font=("Helvetica", 15)),
     sg.Button('Down', size=(15, 5), font=("Helvetica", 15))]
]

# Create the PySimpleGUI window
window = sg.Window('EMG GUI', layout, 
                   size=(screen_width, screen_height), 
                   location=(0, 0), finalize=True, 
                   resizable=True)  # Create a full screen window

# Get the canvas element for plotting
canvas_elem = window['-CANVAS-']  # Access the Canvas element by its key ('-CANVAS-') for embedding the plot

# Start the dynamic plot within the PySimpleGUI window
dynamic_plot(window, canvas_elem)  # Call the function, passing in the window and canvas element for real-time updates
# Close the window when done
window.close()
