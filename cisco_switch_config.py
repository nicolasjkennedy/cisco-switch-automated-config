"""
=============================================================
  Cisco IOS / IOS-XE Switch Configuration Script
  Connection method: PuTTY plink.exe (SSH)
=============================================================

REQUIREMENTS:
  - Python 3.7+
  - PuTTY installed (plink.exe must be accessible)
  - SSH enabled on the switch:
        Switch(config)# ip ssh version 2
        Switch(config)# crypto key generate rsa modulus 2048

USAGE:
  1. Edit the SWITCH_CONFIG section below with your switch details.
  2. Edit the VLAN_CONFIG, INTERFACE_CONFIG, ROUTING_CONFIG, ACL_CONFIG
     sections with your desired settings.
  3. Run: python cisco_switch_config.py
  4. Optional flags:
       --dry-run    Print all commands without sending them
       --section    Run only one section: vlans | interfaces | routing | acls
       Example: python cisco_switch_config.py --dry-run
                python cisco_switch_config.py --section vlans
"""

import subprocess
import sys
import argparse
import time
import getpass

# ─────────────────────────────────────────────────────────────
#  SWITCH CONNECTION SETTINGS  ← Edit these
# ─────────────────────────────────────────────────────────────
SWITCH_CONFIG = {
    "host":         "192.168.1.1",          # Switch IP address or hostname
    "username":     "admin",                 # SSH username
    "password":     "",                      # Leave blank to be prompted at runtime (more secure)
    "enable_pass":  "",                      # Enable / privilege password (leave blank to prompt)
    "plink_path":   "plink",                 # Full path to plink.exe if not in PATH
                                             # e.g. r"C:\Program Files\PuTTY\plink.exe"
    "port":         22,                      # SSH port (default 22)
    "accept_host_key": True,                 # Auto-accept new host key (-batch mode)
}

# ─────────────────────────────────────────────────────────────
#  VLAN CONFIGURATION  ← Edit these
# ─────────────────────────────────────────────────────────────
# Each entry: { "id": <vlan_id>, "name": "<name>" }
VLAN_CONFIG = [
    {"id": 10,  "name": "MANAGEMENT"},
    {"id": 20,  "name": "SERVERS"},
    {"id": 30,  "name": "USERS"},
    {"id": 40,  "name": "VOIP"},
    {"id": 99,  "name": "NATIVE"},
]

# ─────────────────────────────────────────────────────────────
#  INTERFACE CONFIGURATION  ← Edit these
# ─────────────────────────────────────────────────────────────
# mode: "access" | "trunk" | "routed"
# For access: set "access_vlan"
# For trunk:  set "trunk_allowed_vlans" (e.g. "10,20,30") and "native_vlan"
# For routed: set "ip_address" and "subnet_mask"
INTERFACE_CONFIG = [
    {
        "interface":        "GigabitEthernet0/1",
        "description":      "Uplink to Core",
        "mode":             "trunk",
        "trunk_allowed_vlans": "10,20,30,40",
        "native_vlan":      99,
        "shutdown":         False,
    },
    {
        "interface":        "GigabitEthernet0/2",
        "description":      "Server Port",
        "mode":             "access",
        "access_vlan":      20,
        "shutdown":         False,
    },
    {
        "interface":        "GigabitEthernet0/3",
        "description":      "User Workstation",
        "mode":             "access",
        "access_vlan":      30,
        "shutdown":         False,
    },
    {
        "interface":        "Vlan10",
        "description":      "Management SVI",
        "mode":             "routed",
        "ip_address":       "192.168.10.1",
        "subnet_mask":      "255.255.255.0",
        "shutdown":         False,
    },
]

# ─────────────────────────────────────────────────────────────
#  PORT SECURITY CONFIGURATION  ← Edit these
# ─────────────────────────────────────────────────────────────
# Applies only to access-mode interfaces listed above.
# Set "enabled: True" on any interface dict above, and add
# a matching entry here keyed by interface name.
PORT_SECURITY_CONFIG = {
    # "GigabitEthernet0/3": {
    #     "max_mac":          2,              # Max allowed MAC addresses
    #     "violation":        "restrict",     # protect | restrict | shutdown
    #     "sticky":           True,           # Sticky MAC learning
    # },
}

# ─────────────────────────────────────────────────────────────
#  ACL CONFIGURATION  ← Edit these
# ─────────────────────────────────────────────────────────────
# Each ACL has a name/number, type (standard | extended), and a list of rules.
# Apply ACLs to interfaces using the "apply_to" list.
ACL_CONFIG = [
    {
        "name":     "BLOCK_TELNET",
        "type":     "extended",
        "rules": [
            "deny   tcp any any eq 23",
            "permit ip any any",
        ],
        "apply_to": [
            # {"interface": "GigabitEthernet0/1", "direction": "in"},
        ],
    },
    {
        "name":     "MGMT_ACCESS",
        "type":     "standard",
        "rules": [
            "permit 192.168.10.0 0.0.0.255",
            "deny   any log",
        ],
        "apply_to": [],
    },
]

# ─────────────────────────────────────────────────────────────
#  ROUTING CONFIGURATION  ← Edit these
# ─────────────────────────────────────────────────────────────
ROUTING_CONFIG = {
    # ── Static Routes ──────────────────────────────────────
    "static_routes": [
        # {"network": "0.0.0.0", "mask": "0.0.0.0", "next_hop": "192.168.1.254"},  # Default route
        # {"network": "10.0.0.0", "mask": "255.255.255.0", "next_hop": "192.168.1.2"},
    ],

    # ── OSPF ──────────────────────────────────────────────
    "ospf": {
        "enabled":      False,
        "process_id":   1,
        "router_id":    "1.1.1.1",
        "networks": [
            # {"network": "192.168.10.0", "wildcard": "0.0.0.255", "area": 0},
        ],
        "passive_interfaces": [
            # "GigabitEthernet0/2",
        ],
    },

    # ── BGP ──────────────────────────────────────────────
    "bgp": {
        "enabled":  False,
        "asn":      65001,
        "router_id": "1.1.1.1",
        "neighbors": [
            # {"ip": "192.168.1.254", "remote_asn": 65000, "description": "ISP Uplink"},
        ],
        "networks": [
            # {"network": "192.168.10.0", "mask": "255.255.255.0"},
        ],
    },
}


# ═════════════════════════════════════════════════════════════
#  COMMAND BUILDERS  (no editing needed below this line)
# ═════════════════════════════════════════════════════════════

def build_vlan_commands(vlans):
    cmds = ["! --- VLAN Configuration ---"]
    for v in vlans:
        cmds.append(f"vlan {v['id']}")
        cmds.append(f" name {v['name']}")
    cmds.append("exit")
    return cmds


def build_interface_commands(interfaces, port_security):
    cmds = ["! --- Interface Configuration ---"]
    for iface in interfaces:
        name = iface["interface"]
        cmds.append(f"interface {name}")
        if "description" in iface:
            cmds.append(f" description {iface['description']}")

        mode = iface.get("mode", "access")

        if mode == "trunk":
            cmds.append(" switchport mode trunk")
            if "native_vlan" in iface:
                cmds.append(f" switchport trunk native vlan {iface['native_vlan']}")
            if "trunk_allowed_vlans" in iface:
                cmds.append(f" switchport trunk allowed vlan {iface['trunk_allowed_vlans']}")
            cmds.append(" no shutdown" if not iface.get("shutdown") else " shutdown")

        elif mode == "access":
            cmds.append(" switchport mode access")
            if "access_vlan" in iface:
                cmds.append(f" switchport access vlan {iface['access_vlan']}")

            # Port security (access only)
            if name in port_security:
                ps = port_security[name]
                cmds.append(" switchport port-security")
                if "max_mac" in ps:
                    cmds.append(f" switchport port-security maximum {ps['max_mac']}")
                if ps.get("sticky"):
                    cmds.append(" switchport port-security mac-address sticky")
                if "violation" in ps:
                    cmds.append(f" switchport port-security violation {ps['violation']}")

            cmds.append(" no shutdown" if not iface.get("shutdown") else " shutdown")

        elif mode == "routed":
            cmds.append(" no switchport")
            if "ip_address" in iface:
                cmds.append(f" ip address {iface['ip_address']} {iface['subnet_mask']}")
            cmds.append(" no shutdown" if not iface.get("shutdown") else " shutdown")

        cmds.append("exit")
    return cmds


def build_acl_commands(acls):
    cmds = ["! --- ACL Configuration ---"]
    for acl in acls:
        acl_type = acl.get("type", "extended")
        name = acl["name"]
        if acl_type == "extended":
            cmds.append(f"ip access-list extended {name}")
        else:
            cmds.append(f"ip access-list standard {name}")
        for rule in acl.get("rules", []):
            cmds.append(f" {rule}")
        cmds.append("exit")

        # Apply to interfaces
        for app in acl.get("apply_to", []):
            cmds.append(f"interface {app['interface']}")
            cmds.append(f" ip access-group {name} {app['direction']}")
            cmds.append("exit")
    return cmds


def build_routing_commands(routing):
    cmds = ["! --- Routing Configuration ---"]

    # Static routes
    for route in routing.get("static_routes", []):
        cmds.append(f"ip route {route['network']} {route['mask']} {route['next_hop']}")

    # OSPF
    ospf = routing.get("ospf", {})
    if ospf.get("enabled"):
        cmds.append(f"router ospf {ospf['process_id']}")
        if "router_id" in ospf:
            cmds.append(f" router-id {ospf['router_id']}")
        for net in ospf.get("networks", []):
            cmds.append(f" network {net['network']} {net['wildcard']} area {net['area']}")
        for pi in ospf.get("passive_interfaces", []):
            cmds.append(f" passive-interface {pi}")
        cmds.append("exit")

    # BGP
    bgp = routing.get("bgp", {})
    if bgp.get("enabled"):
        cmds.append(f"router bgp {bgp['asn']}")
        if "router_id" in bgp:
            cmds.append(f" bgp router-id {bgp['router_id']}")
        for neighbor in bgp.get("neighbors", []):
            cmds.append(f" neighbor {neighbor['ip']} remote-as {neighbor['remote_asn']}")
            if "description" in neighbor:
                cmds.append(f" neighbor {neighbor['ip']} description {neighbor['description']}")
        for net in bgp.get("networks", []):
            cmds.append(f" network {net['network']} mask {net['mask']}")
        cmds.append("exit")

    return cmds


def build_all_commands(sections="all"):
    """Assemble all IOS config commands into a single list."""
    commands = ["configure terminal"]

    if sections in ("all", "vlans"):
        commands += build_vlan_commands(VLAN_CONFIG)

    if sections in ("all", "interfaces"):
        commands += build_interface_commands(INTERFACE_CONFIG, PORT_SECURITY_CONFIG)

    if sections in ("all", "acls"):
        commands += build_acl_commands(ACL_CONFIG)

    if sections in ("all", "routing"):
        commands += build_routing_commands(ROUTING_CONFIG)

    commands += [
        "end",
        "write memory",   # Save config (wr mem)
    ]
    return commands


# ═════════════════════════════════════════════════════════════
#  PLINK TRANSPORT
# ═════════════════════════════════════════════════════════════

def send_via_plink(commands, password, enable_pass, dry_run=False):
    """
    Send IOS commands to the switch using plink.exe.
    plink sends a script file over stdin.
    """
    cfg = SWITCH_CONFIG

    # Build the full command sequence including enable
    full_sequence = []
    if enable_pass:
        full_sequence += ["enable", enable_pass]
    full_sequence += commands

    script = "\n".join(full_sequence) + "\n"

    if dry_run:
        print("\n" + "=" * 60)
        print("  DRY RUN — Commands that WOULD be sent to the switch:")
        print("=" * 60)
        for line in full_sequence:
            print(f"  {line}")
        print("=" * 60)
        print("  Dry run complete. No changes were made.")
        return True

    # Build plink command
    plink_cmd = [
        cfg["plink_path"],
        "-ssh",
        "-l", cfg["username"],
        "-pw", password,
        "-P", str(cfg["port"]),
    ]
    if cfg.get("accept_host_key"):
        plink_cmd.append("-batch")  # Auto-accept host key (first connection)

    plink_cmd.append(cfg["host"])

    print(f"\n[*] Connecting to {cfg['host']}:{cfg['port']} as '{cfg['username']}' ...")

    try:
        result = subprocess.run(
            plink_cmd,
            input=script.encode(),
            capture_output=True,
            timeout=60,
        )

        output = result.stdout.decode(errors="replace")
        errors = result.stderr.decode(errors="replace")

        print("\n── Switch Output ──────────────────────────────────────")
        print(output if output.strip() else "(no output)")

        if errors.strip():
            print("\n── Warnings / Errors ──────────────────────────────────")
            print(errors)

        if result.returncode != 0:
            print(f"\n[!] plink exited with code {result.returncode}")
            return False

        print("\n[✓] Configuration applied successfully!")
        return True

    except FileNotFoundError:
        print("\n[ERROR] plink.exe not found!")
        print("  → Install PuTTY from https://www.putty.org/")
        print(f"  → Or set 'plink_path' to the full path, e.g.: r'C:\\Program Files\\PuTTY\\plink.exe'")
        return False
    except subprocess.TimeoutExpired:
        print("\n[ERROR] Connection timed out. Check the switch IP and SSH settings.")
        return False
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        return False


# ═════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Cisco IOS/IOS-XE Switch Configuration via PuTTY plink"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print commands without sending them to the switch"
    )
    parser.add_argument(
        "--section", default="all",
        choices=["all", "vlans", "interfaces", "acls", "routing"],
        help="Run only a specific config section (default: all)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Cisco IOS/IOS-XE Switch Configuration Script")
    print("=" * 60)
    print(f"  Target  : {SWITCH_CONFIG['host']}:{SWITCH_CONFIG['port']}")
    print(f"  User    : {SWITCH_CONFIG['username']}")
    print(f"  Section : {args.section}")
    print(f"  Mode    : {'DRY RUN' if args.dry_run else 'LIVE'}")
    print("=" * 60)

    # Collect passwords securely at runtime if not hardcoded
    password = SWITCH_CONFIG.get("password") or getpass.getpass("SSH password: ")
    enable_pass = SWITCH_CONFIG.get("enable_pass") or getpass.getpass("Enable password (blank if none): ")

    commands = build_all_commands(sections=args.section)

    success = send_via_plink(
        commands,
        password=password,
        enable_pass=enable_pass,
        dry_run=args.dry_run,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
