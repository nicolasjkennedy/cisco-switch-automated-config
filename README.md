# cisco-switch-automated-config
<img width="1250" height="840" alt="image" src="https://github.com/user-attachments/assets/eb63113a-9811-4f84-8072-50ca33054c84" />

**Setup (one-time)**
Install PuTTY — plink.exe comes bundled with it
Make sure SSH is enabled on your switch (ip ssh version 2)
No extra Python libraries needed — it uses only the standard library

Configure the script — edit the clearly-labelled sections at the top:
Run it
bash# Preview all commands without touching the switch
python cisco_switch_config.py --dry-run

# Apply everything
python cisco_switch_config.py

# Apply only one section
python cisco_switch_config.py --section vlans
python cisco_switch_config.py --section interfaces
python cisco_switch_config.py --section routing
python cisco_switch_config.py --section acls
