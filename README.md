# Biomedical engineering projects

Python and Arduino code from three medical technology projects I built while studying Biomedical Engineering (Honours) and Medical Science at the University of Sydney. Each folder holds one project. The sections below explain why it was built, what it does, my part in it and how to run it.

## Projects

* **Cochlear implant sound processing simulator** (folder `Advanced Bionics`): turns any sound into stimulation for a 16 electrode cochlear implant with three clinical coding strategies, so you can see and hear what each one keeps.
* **Muscle Maestro** (folder `Biomedical Instrumentation`): an EMG device that moves a servo when you flex your biceps, with a live plotting interface.
* **Pulse4U** (folder `Computational Analysis of Biomedical Signals`): a wearable heart rate monitor that detects each beat on an ESP32 and streams to a desktop app with alarms.

## Cochlear implant sound processing simulator

**Why I built it.** A cochlear implant has to describe rich sound with pulses on just 16 electrodes, and the coding strategy decides what the listener keeps and what is lost. I wanted to compare the main strategies on the same sound, both visually and by ear.

**What it does**

* Loads a WAV file or records 10 seconds from the microphone, resamples it to 16 kHz and splits it into 2 ms epochs.
* Turns each epoch into stimulation levels for 16 electrodes with one of three strategies:
  * **F0F1F2** finds the formants with linear predictive coding (Levinson Durbin recursion) and maps them to the nearest electrodes.
  * **CIS** (continuous interleaved sampling) uses a bank of 16 fourth order Butterworth band pass filters from 200 to 7,000 Hz with Hilbert envelopes.
  * **ACE** (advanced combination encoder) keeps only the strongest channels in each epoch: 8 of 16 by default, adjustable in the app.
* Compresses the levels into a 10 dB dynamic range (323 to 1,024 charge units) and draws an electrodogram of the stimulation over time.
* Plays the original sound next to a vocoder rebuild of the stimulation, which approximates what the strategy keeps.
* Exports the stimulation matrix as CSV and the vocoder audio as WAV.

**My part.** I designed and wrote the whole program, including the interface.

**Built with.** Python, NumPy, SciPy, Matplotlib and Tkinter. The sounddevice package is optional: it adds microphone recording and is used for playback when installed.

**Run it** (Python 3.9 or newer)

```
pip install numpy scipy matplotlib sounddevice
cd "Advanced Bionics"
python Cochlear_Implant_sound_processing_simulator.py
```

Tkinter ships with most Python installers. On Linux, install your distribution's Tkinter package if the window does not open.

## Muscle Maestro: an EMG controlled servo

**Why we built it.** Muscle activity measured on the skin is tiny and noisy. We wanted to take it all the way from electrode to movement: amplify and filter it in hardware, detect a contraction in firmware and use it to drive a motor, the same principle a myoelectric prosthesis relies on.

**What it does**

* Surface electrodes on the biceps feed an analogue front end with an instrumentation amplifier and a band pass filter.
* An Arduino samples the conditioned signal, checks a rolling window of the last 10 samples against a threshold band, and turns a servo while the muscle is active and back when it relaxes.
* A desktop interface plots the signal live, with zoom, pause and vertical shift controls, and logs the samples to `emg_data.csv`.
* A separate script calculates the signal to noise ratio from three rest and contraction pairs in a recording.

**My part.** I led our team of four through the design, circuit simulation and stage by stage testing.

**Built with.** Arduino (C++), Python, PySimpleGUI, Matplotlib, pyserial, pandas and NumPy. The circuit was designed in LTspice; those files are not included.

**Run it**

1. Upload the Arduino sketch in this folder to the board.
2. In the GUI script, set `COM_PORT` to your board's serial port.
3. Install the packages, then run the GUI script from this folder:

   ```
   pip install PySimpleGUI matplotlib pyserial pandas numpy
   ```

4. To measure the signal to noise ratio, place a recording named `emg_data.csv` next to `Muscle Maestro SNR.py` and run it. The time windows in the script match our recording protocol, so change them for your own data. Recordings are not included.

## Pulse4U: a wearable heart rate monitor

**Why we built it.** We wanted a wearable that finds each heartbeat on the device itself, sends the result wirelessly and tells the user when a reading looks wrong.

**What it does**

* An ESP32 samples a PPG pulse sensor every 20 ms (50 Hz).
* An adaptive threshold, set at 70% of the signal range over the last 2 seconds, detects each beat and gives beats per minute, so detection keeps working as the signal strength changes.
* Once a second, the firmware packs 50 readings, a packet number and the heart rate into one message and sends it over Bluetooth. An LED flashes with each transfer.
* The desktop app plots heart rate and the raw pulse live, shows the average, minimum and maximum, raises alarms above 135 bpm or below 40 bpm, and warns when no data has arrived for 5 seconds.

**My part.** In our team of three, I wrote the adaptive threshold beat detector and the Bluetooth link, including the connection callback and status LED, and merged the team's firmware into one program.

**Built with.** ESP32, Arduino (C++), Bluetooth serial, Python, PySimpleGUI, Matplotlib, NumPy and pyserial.

**Run it**

1. Open the sketch in the Arduino IDE with the ESP32 board package installed. It also needs a small debounce helper, `switch.h`, which is not part of this repository.
2. Upload it, then pair your computer with the ESP32 over Bluetooth.
3. In `Pulse4U.py`, set `portName` to the ESP32's Bluetooth serial port, then run:

   ```
   pip install PySimpleGUI matplotlib numpy pyserial
   python Pulse4U.py
   ```

4. Press the button on the device to start or stop reading.

`LED_2pythonScript.py` is an early test script for the serial link.

## About this code

* These are student projects, shared so employers and collaborators can see how I work. They are not medical devices and must not be used for diagnosis or treatment.
* The code is not licensed for reuse. Please ask before using any part of it, and do not submit any of it for assessment.

## Contact

Carlos Jorges · [LinkedIn](https://www.linkedin.com/in/carlos-jorges-573319202)
