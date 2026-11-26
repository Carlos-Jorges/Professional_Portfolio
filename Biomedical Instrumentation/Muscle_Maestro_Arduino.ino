#include <Servo.h>

// Define constants
const int inputPin = A1;       // Pin connected to the thermistor (Vout)
const float Vcc = 5.0;         // Supply voltage (Vin)
const int servoPin = A2;       // Pin connected to the servo signal
const float upperthreshold = 2.45;   // Threshold for comparison
const float lowerthreshold = 2.25;
const int maxSize = 10;        // Fixed size for the value array

int time_1;
int time_2;
int time_final;

float valuelist[maxSize];      // Array to store the last 50 values
int index = 0;                 // Index to track the position in the array
bool higher = false;           // Boolean to track if any value exceeds threshold

Servo myServo;                 // Create a Servo object
int oldServoAngle = 0;         // Variable to store the previous servo angle
int servoAngle = 0;            // Initialize servoAngle

void setup() {
    Serial.begin(9600);         // Start serial communication
    pinMode(inputPin, INPUT);   // Set the input pin as input
    myServo.attach(servoPin);   // Attach the servo control signal to pin A2
}

void loop() {
    // Read the analog value from the input pin (Vout)
    time_1= micros();
    int adcValue = analogRead(inputPin);
    float Vout = adcValue * (Vcc / 1023.0);  // Convert ADC to voltage

    // Store the new value in the array
    valuelist[index] = Vout;
    index = (index + 1) % maxSize;  // Wrap around the index when it reaches maxSize

    // Check if any value in the array exceeds the threshold
    higher = false;  // Reset the 'higher' flag
    for (int i = 0; i < maxSize; i++) {
        if (valuelist[i] >= upperthreshold || valuelist[i] <= lowerthreshold) {
            higher = true;
            break;  // Exit the loop as soon as we find a value above the threshold
        }
    }

    // Modify the servo angle based on the condition
    if (higher) {
        servoAngle += 4;  // Increment angle if condition is met
    } else {
        servoAngle -= 4;  // Decrement angle if condition is not met
    }

    // Constrain the servo angle within valid limits (0 to 180 degrees)
    servoAngle = constrain(servoAngle, 0, 180);

    // Move the servo only if the angle has changed
    if (servoAngle != oldServoAngle) {
        myServo.write(servoAngle);       // Move the servo to the new angle
        oldServoAngle = servoAngle;      // Update the old servo angle
    }

    // Print the voltage and servo angle to the Serial Monitor
    Serial.println(Vout);
    //Serial.print(", ");
    //Serial.println(servoAngle);

    time_2= micros();
    time_final = time_2 - time_1;
    //Serial.println(time_final);
    delay(100);  // Delay for a more readable output
}
