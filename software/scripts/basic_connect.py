"""
basic_connect.py

Purpose:
This script demonstrates USB connection to a Tektronix
MSO-series oscilloscope using PyVISA with the pyvisa-py backend.

It performs the following steps:
- Discovers connected USB instruments via PyVISA
- Opens a connection to the first USB oscilloscope found
- Queries the instrument identification string (*IDN?)
- Reads and modifies the vertical position of Channel 1
- Closes the connection cleanly

Key concepts:
- PyVISA provides a high-level API for communicating with instruments using SCPI.
- The pyvisa-py backend communicates with USB instruments using libusb.
- SCPI commands are sent as strings (e.g., "CH1:POSition -2.0").

Notes:
- This script is intended as a known-good baseline for future scope automation.
- .write() sends a command to the instrument without expecting a response.
- .query() sends a command and waits for a response from the instrument. Shorthand for .write() followed by .read().
- .strip() removes whitespace/newlines so printing looks clean. 
- Tested on Tektronix MSO58 over USB from a Raspberry Pi.
"""


import time
import pyvisa

def connect_scope():
    rm = pyvisa.ResourceManager("@py") # Use the PyVISA-py backend

    while True: # Keep trying to connect until a scope is found
        resources = rm.list_resources() # List all connected resources
        usb = [r for r in resources if r.startswith("USB")] # Find USB resources

        if usb: # If any USB resources are found
            scope = rm.open_resource(usb[0]) # Connect to the first USB scope found
            scope.timeout = 5000 # Set timeout to 5 seconds
            scope.write_termination = "\n" # Set write termination. SCPI commands end with newline
            scope.read_termination = "\n" # Set read termination. SCPI responses end with newline
            return scope # Return the connected scope
        print("No USB scope found, retrying in 2s...")
        time.sleep(2) # Wait before retrying

def main():
    scope = connect_scope() # Connect to the oscilloscope
    idn = scope.query("*IDN?").strip() # Query the identification string
    print("Connected:", idn)

    print("CH1 pos was:", scope.query("CH1:POSition?").strip()) # Query current CH1 position
    scope.write("CH1:POSition -2.0") # Set CH1 position to -2.0
    print("CH1 pos is:", scope.query("CH1:POSition?").strip()) # Query new CH1 position

    scope.close() # Close the VISA connection cleanly


# Only run main() if this script is executed directly. 
# This allows importing this script's functions into other scripts without auto-running main().
if __name__ == "__main__": 
    main()
