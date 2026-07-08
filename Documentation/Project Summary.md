Project Summary
	The current running idea is a microcontroller powered system that turns on and off the machine by tapping into the main disconnect switch. Students access the machine via two factor authentication, an RFID card and a PIN number. When these are entered, the microcontroller allows access to the main disconnect for the machine to be turned on. Two cameras also reside in the system, one for security footage outside the machine, the other inside the machine for remote monitoring and marketing material.
	The microcontroller will host a website that logs all data in and out of the system. Admins can access this data, while normal students can also login to the website for a certification process.

•	Electrical
  o	Relay taps into the main disconnect line, for turning on and off the machine.
  o	Module attached to side of PathPilot Console
    -	Raspberry Pi Pico w/ Wifi OR ESP32
    -	PIN Pad
    -	RFID Card Reader
    -	LED Indicators
  o	Plugs into wall for power.
    -	5v?
  o	Custom PCBs are an option, requires Fusion Electronics Workspace
  o	Camera on PathPilot Console for Security Footage
  o	Camera inside Tormach for remote monitoring and marketing material (timelapses)
  o	Air compressor needs adapter for accessory plug into the electrical cabinet for automatic activation
•	Mechanical
  o	M3 Bolt Holes on side of PathPilot Console
  o	Plenty of room in Tormach’s electrical cabinet for main disconnect.
•	Software
  o	Microcontroller of choice hosts a website
    -	Website holds logs of all user actions
    -	Admin access
    -	Also hosts certification program, however that’s developed.
