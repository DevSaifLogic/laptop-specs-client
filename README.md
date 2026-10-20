# Laptop Specs Client

A Windows utility that reads hardware and system details through PowerShell and posts the resulting inventory record to the Laptop Specs Server.

## Run

Requires Windows PowerShell and Python 3.10+.

1. Start the [Laptop Specs Server](../main/README.md) on a trusted machine.
2. Create an environment and install dependencies:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```
3. Set `LAPTOP_SPECS_SERVER_URL` if the receiver is not on this computer:

   ```powershell
   $env:LAPTOP_SPECS_SERVER_URL = "http://127.0.0.1:8080/"
   $env:LAPTOP_SPECS_LOCATION = "Optional inventory location"
   python main.py
   ```

The collected record can include a Windows product key, BIOS serial, product ID, machine ID, computer name, and hardware details. Run only on devices you own or are authorized to inventory, confirm the receiver address before sending, and do not expose the unauthenticated HTTP receiver to an untrusted network.
