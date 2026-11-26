#define BAUDRATE 115200

//Libraries
#include "BluetoothSerial.h"//library used for Bluetooth interactions
#include <Esp.h>//library used for the ESP
#include "switch.h"//library used for adaptive threshold and HR calculations

//Bluetooth by Carlos
#if !defined(CONFIG_BT_ENABLED) || !defined(CONFIG_BLUEDROID_ENABLED)
#error Bluetooth is not enabled! Please run `make menuconfig` to and enable it
#endif
String btName = "ESP32_Carlos_J."; // device name 
BluetoothSerial SerialBT;//used to create Bluetooth serial object and establish communication 

//Components
#define LED_PIN1 13//button behaviour
#define LED_PIN3 32//package data
#define SWITCH_PIN 33
#define SENSOR_PIN 25

//Button and LED1 Behaviour by Pranjali
#define TICK_TIME 10// delay for the switch behaviou define delay global variables in ms
#define LED_BLINK_TIME 300// delay for the LED1 write behaviour
#define DEBOUNCE_COUNT 10// delay for the switch recognition
Switch switch_1(1, DEBOUNCE_COUNT);
bool sensor_is_reading = false; 
int sensor_sample = 0;

//Communications and LED_3 behaviour by Carlos
#define LENGTH_STRING 256//#of packet and the comma (3 digits), 50x5 (4 digits number and the comma), HR (3 digits) 
#define SAMPLE_FREQ 50//also used in adaptive threshold in HZ
long time_1;
long time_2;
int count = 0;//counter used to append the signal readers to the string
uint16_t recording = 0; //variable to be used for storing sensor signals
int package_num = 1;//variable to store the package number
char buf_1[LENGTH_STRING];
int openEvt = 0;//integer valye to indicate if a Bluetooth event has taken place
char mock_HR[3] = "HR";//mock HR value used for testing
bool LED_state3 = false;//required to initially have the LED off

//Adaptive threshold by Carlos
#define DEBUG true// switch to debug output depending what is wanting to be visualise the threshold and read data (true=waveform, false=BPM)
#define ADAPTIVE_WINDOW 2// length of time (seconds) over which adaptive window is calculated
#define ADAPTIVE_RATIO 70// percent of signal range (in ADAPTIVE_WINDOW) that threshold will be set to
const uint16_t sample_period = (int)1000000/SAMPLE_FREQ;
const uint16_t adaptive_buf_len = ADAPTIVE_WINDOW*SAMPLE_FREQ;
uint16_t adaptive_buf[adaptive_buf_len];// buffer for adaptive threshold calculation
Switch pulse(1, 1);// used to detect rising edge of pulse
// dynamic valariables (within Adaptive threshold)
uint16_t threshold_val = 0;
uint16_t sensor_val = 0;
unsigned long AT_loop_start = 0;
unsigned long curr_transition = 0;
unsigned long prev_transition = 0;
unsigned long pulse_period = 0;
float pulse_rate = 0;
// functions (for Adaptive threshold)
uint16_t get_threshold(uint16_t* adaptive_buf, uint16_t sensor_val);
uint16_t get_max(uint16_t* buf, uint16_t buf_len);
uint16_t get_min(uint16_t* buf, uint16_t buf_len);

void setup() // the setup function runs once when you press reset or power the board, by Carlos and Pranjali(while loop and LED1 behaviour)
{ 
  pinMode(LED_PIN1, OUTPUT);
  pinMode(LED_PIN3, OUTPUT);
  pinMode(SWITCH_PIN, INPUT_PULLDOWN);// initialize digital pins
  Serial.begin(BAUDRATE);

  Serial.println("****************************");
  Serial.println("* ESP Bluetooth SLAVE DEMO *");
  Serial.println("****************************");
  Serial.println("\nNow run the host program...");

  SerialBT.register_callback(btCallback);

  SerialBT.begin(btName);//initialise Bluetooth

  if (!SerialBT.begin(btName))
  {
    Serial.println("An error occurred initializing Bluetooth");//for printing error messages if the Bluetooth initialisation fails
  }
  else
  {
    Serial.println("Bluetooth initialized");
    Serial.println(btName);//printing the above message to indicate Bluetooth connection establish with the device under btName
  }
  time_1 = micros();//getting a time tick when board is initialised

  while(!digitalRead(SWITCH_PIN))//read switch push
  {
    delay(TICK_TIME);
  }
}

void loop() 
{
  
  switch_1.update(digitalRead(SWITCH_PIN));//Switch (used for debouncing switch behaviour and enabling the sensor) by Pranjali
  
  if(switch_1.changed() && switch_1.state())// if the switch state is changed 
  {
    sensor_is_reading = !sensor_is_reading;// disable/enable the sensor depending on current state
  }

  if (sensor_is_reading) 
  {
    digitalWrite(LED_PIN1, HIGH);

    //Adaptive threshold by Carlos
    AT_loop_start = micros();
    sensor_val = analogRead(SENSOR_PIN);
    threshold_val = get_threshold(adaptive_buf, adaptive_buf_len, sensor_val);
    pulse.update(sensor_val > threshold_val);
    
    if (pulse.changed() && pulse.state())// detect rising edge and calculate pulse rate using the current time tick and the one calculated in the previous rising edge 
    {
      curr_transition = millis();
      pulse_period = curr_transition - prev_transition;
      pulse_rate = 60000./((float)pulse_period);
      prev_transition = curr_transition;//reset the previous time tick to the value of the current before the loop is ran again
    }

    //Dictating the mode in which Adaptive threshold is used and the display within the Arduino Serial monitor and plotter by Carlos
    if (!DEBUG)
    {
      Serial.printf("%0.1f\n", pulse_rate);// print pulse rate in bpm
    } 
    else
    {
      Serial.printf("%d,%d\n", sensor_val, threshold_val);//print sensor raw data
    }
  
    //Communications by Carlos
    LED_state3 = false;
    digitalWrite(LED_PIN3, LED_state3);

    if (count == 0)//Initial value for the package_number (two-digit number) appended to the beggining of the buf_1 followed by the respective comma when count variable is 0, then incrementing it by 3(2 digits and the comma)
    {
      sprintf(buf_1, "%02d",package_num);
      package_num = (package_num +1)%10;
      buf_1[2] = ','; 
      count = (count + 3);
    }

    time_2 = micros();
    if((time_2 - time_1) > 1000000/SAMPLE_FREQ)//difference between time_2 and time_1 calculated to ensure that samples are taken at 20 ms intervals and consequently appending sensor reading(four-digit number) to the buf_1 and the respective comma, then increments the count number by 5 (4 digits and the comma)
    {
      recording = analogRead(SENSOR_PIN);
      sprintf(buf_1 + count, "%04d", recording);
      buf_1[count + 4] = ',';
      count = (count + 5);
          
      if (count == (LENGTH_STRING - 3))//when the count variable reaches a value of 253 (i.e. the package_num and the 50 data readings have been appended), then the heart in bpm (3 digit number) is appended and the buf_1 sent via Bluetooth once a second. The count variable is reset to 0
      {
        sprintf(buf_1 + count, "%0.1f\n", pulse_rate);
        count = 0;
        //Serial.printf("%s\n", buf_1);//to print out the packaged data before sending it through Bluetooth used during testing
        //Serial.printf("LED_state3 (loop): %d\n", LED_state3); // used to test whether the LED state was 0 or 1 activate for BT communication
        SerialBT.write((const uint8_t*)buf_1, LENGTH_STRING);
        SerialBT.write((const uint8_t*)"\n", 1);
        if (package_num == 0)// when the package_num reaches 10 the modulo makes its value = 0, so the package_num value is turned to 1 to prevent the packaging number from being 0
          package_num = 1;     
      }

      time_1 = time_2;//the time_1 tick is set the time_2 to the latest before closing the loop so that it can be used for the next iteration     
    }

    digitalWrite(LED_PIN3, LED_state3);
    delayMicroseconds(sample_period  - (AT_loop_start - micros()));// delay to maintain sample period of the adaptive threshold
  }

  else// if the switch state has not been changed by Pranjali
  {
    digitalWrite(LED_PIN1, LOW);
  }
  delay(TICK_TIME);
}


void btCallback(esp_spp_cb_event_t event, esp_spp_cb_param_t *param)// This function displays SPP events when they occur. This provides information on what is hapening on the bluetooth link and allows the user to visualise it via the LED whilst also printing a message in the serial monitor to indicate the action taking place by Carlos
{
  LED_state3 = true;
  digitalWrite(LED_PIN3, LED_state3);
  //Serial.printf("LED_state3 (btCallback): %d\n", LED_state3);// used to display when the LED is turned on
  
  if (event == ESP_SPP_SRV_OPEN_EVT) 
  {
    char buf[50];
    openEvt++;
    sprintf(buf, "Client Connected:%d", openEvt);
    Serial.println(buf);
    Serial.print("  Address = ");
    for (int i = 0; i < 6; i++)
    {
      sprintf(&(buf[i * 3]), "%02X:", param->srv_open.rem_bda[i]);
    }
    buf[17] = 0;
    Serial.println(buf);
  }

  if (event == ESP_SPP_INIT_EVT)
    Serial.println("ESP_SPP_INIT_EVT");
  else if (event == ESP_SPP_UNINIT_EVT)
    Serial.println("ESP_SPP_INIT_EVT");
  else if (event == ESP_SPP_DISCOVERY_COMP_EVT )
    Serial.println("ESP_SPP_DISCOVERY_COMP_EVT");
  else if (event == ESP_SPP_OPEN_EVT ) 
    Serial.println("ESP_SPP_OPEN_EVT");
  else if (event == ESP_SPP_CLOSE_EVT )
    Serial.println("ESP_SPP_CLOSE_EVT");
  else if (event == ESP_SPP_START_EVT )
    Serial.println("ESP_SPP_START_EVT");
  else if (event == ESP_SPP_CL_INIT_EVT )
    Serial.println("ESP_SPP_CL_INIT_EVT");
  else if (event == ESP_SPP_DATA_IND_EVT )
    Serial.println("ESP_SPP_DATA_IND_EVT");
  else if (event == ESP_SPP_CONG_EVT )
    Serial.println("ESP_SPP_CONG_EVT");
  else if (event == ESP_SPP_WRITE_EVT )
    Serial.println("ESP_SPP_WRITE_EVT");
  else if (event == ESP_SPP_SRV_OPEN_EVT )
    Serial.println("ESP_SPP_SRV_OPEN_EVT");
  else if (event == ESP_SPP_SRV_STOP_EVT )
    Serial.println("ESP_SPP_SRV_STOP_EVT");
  else
  {
    Serial.print("EV: ");
    Serial.println(event);
  }
}

/*
 * Stores new values in a ring buffer, then calculates a new threshold value for pulse detection by finding the 'ADAPTIVE_RATIO' percent of the range of values in buf.
 * Arguments:
 * * buf: an array of uint16_t values ranging from 0 to 4095.
 * * buf_len: length of buf.
 * * new_val: the new val to be added to buf.
 * Returns: updated threshold value.
 */
uint16_t get_threshold(uint16_t* buf, uint16_t buf_len, uint16_t new_val) //by Carlos
{
  static uint16_t i = 0;
  buf[i] = new_val;
  i = (i + 1) % (buf_len);
  uint16_t max_val = get_max(buf, buf_len);
  uint16_t min_val = get_min(buf, buf_len);
  uint16_t range = max_val - min_val;

  return min_val + (ADAPTIVE_RATIO*range)/100;// calculates the adaptive threshold by adding the predeterined adaptive ratio (70%) to the minimum value    
}

/*
 * Returns the maximum value in a uint16_t array. Assumes min possible value is 0 so as to always get the highest possible value.
 * Arguments:
 * * buf: pointer to the start of the array.
 * * len: length of the array.
 * Returns: max value in the array.
 */
uint16_t get_max(uint16_t* buf, uint16_t buf_len)//by Carlos
{  
  uint16_t max_val = 0;
  for (int i = 0; i < buf_len; i++) 
  {
    max_val = max(max_val, buf[i]);
  }
  return max_val;
}

/*
 * Returns the minimum value in a uint16_t array. Assumes max possible value is 4096 so as to always return the lowest possible value.
 * Arguments:
 * * buf: pointer to the start of the array.
 * * len: length of the array.
 * Returns: min value in the array.
 */
uint16_t get_min(uint16_t* buf, uint16_t buf_len) //by Carlos
{ 
  uint16_t min_val = 4097; 
  for (int i = 0; i < buf_len; i++) 
  {
    min_val = min(min_val, buf[i]);
  }
  return min_val;
}
