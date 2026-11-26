import numpy as np
import pandas as pd

# Load the uploaded CSV file 
emg_data = pd.read_csv('emg_data.csv')

# Create a variable for each column
timestamps = emg_data.iloc[:, 0]
emg_amplitude = emg_data.iloc[:, 1]

# Segment the data into baseline noise (relaxaition) and signal (contraction)
baseline_segment = emg_amplitude[(timestamps >= 0) & (timestamps <= 9)].to_numpy()  # Convert to NumPy array
signal_segment = emg_amplitude[(timestamps >= 9) & (timestamps <= 13)].to_numpy()  # Convert to NumPy array

baseline_segment2 = emg_amplitude[(timestamps >= 13) & (timestamps <= 17.5)].to_numpy()  # Convert to NumPy array
signal_segment2 = emg_amplitude[(timestamps >= 17.5) & (timestamps <= 21.5)].to_numpy()  # Convert to NumPy array

baseline_segment3 = emg_amplitude[(timestamps >= 21.5) & (timestamps <= 25)].to_numpy()  # Convert to NumPy array
signal_segment3 = emg_amplitude[(timestamps >= 25) & (timestamps <= 28.5)].to_numpy()  # Convert to NumPy array

# Function to calculate the power of the signal amplitude
def signalPower(x):
    return np.mean(x**2)

# Calculate SNR of first relaxation-contraction pair (0-13 seconds)
power_signal = signalPower(signal_segment)
power_noise = signalPower(baseline_segment)
SNR = 10*np.log10((power_signal/power_noise))

# Calculate SNR of second relaxation-contraction pair (13-21.5 seconds)
power_signal2 = signalPower(signal_segment2)
power_noise2 = signalPower(baseline_segment2)
SNR2 = 10*np.log10((power_signal2/power_noise2))

# Calculate SNR of third relaxation-contraction pair (21.5-28.5 seconds)
power_signal3 = signalPower(signal_segment3)
power_noise3 = signalPower(baseline_segment3)
SNR3 = 10*np.log10((power_signal2/power_noise3))

# Average all three SNRs
SNR_avg = (SNR + SNR2 + SNR3)/3

print(f"SNR 1: {SNR:.3f} dB")
print(f"SNR 2: {SNR2:.3f} dB")
print(f"SNR 3: {SNR3:.3f} dB")
print(f"Average SNR: {SNR_avg:.3f} dB")
