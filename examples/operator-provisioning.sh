#!/usr/bin/env bash
#
# Operator provisioning for cross-organization deployment on a single shared host.
#
# Creates a scoped UNIX account for the second operator's agent, with:
#   - shared group "deaddrop" with setgid on project dir
#   - SSH key-only login (no password)
#   - traversal-only ACL on host operator's home (cannot ls, can cd through)
#   - no sudo, no docker, no port forwarding, no agent forwarding
#
# Run as root on the shared host. Edit variables at the top before running.

set -euo pipefail

# ===== CONFIG =====
OPERATOR_HOST_USER=admin                                            # the host operator's account
GUEST_USER=guestagent                                               # the guest operator's account
SHARED_GROUP=deaddrop                                                # group both will share
PROJECT_DIR=/home/${OPERATOR_HOST_USER}/Source/shared-project       # the dir both can write
GUEST_PUBKEY="ssh-ed25519 AAAA... guest@host"                        # paste real pubkey
SSHD_DROPIN=/etc/ssh/sshd_config.d/${GUEST_USER}.conf
# ==================

# 1. Group + accounts
groupadd -f "$SHARED_GROUP"
id -u "$GUEST_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$GUEST_USER"
usermod -aG "$SHARED_GROUP" "$GUEST_USER"
usermod -aG "$SHARED_GROUP" "$OPERATOR_HOST_USER"

# 2. Project dir: group ownership + setgid + permissions
mkdir -p "$PROJECT_DIR"
chgrp -R "$SHARED_GROUP" "$PROJECT_DIR"
chmod -R g+rwX "$PROJECT_DIR"
find "$PROJECT_DIR" -type d -exec chmod g+s {} +

# 3. Traversal-only ACL on operator home (guest can cd through, not ls)
setfacl -m "u:${GUEST_USER}:--x" "/home/${OPERATOR_HOST_USER}"

# 4. SSH pubkey-only auth for guest
install -d -m 700 -o "$GUEST_USER" -g "$GUEST_USER" "/home/${GUEST_USER}/.ssh"
printf "%s\n" "$GUEST_PUBKEY" > "/home/${GUEST_USER}/.ssh/authorized_keys"
chown "${GUEST_USER}:${GUEST_USER}" "/home/${GUEST_USER}/.ssh/authorized_keys"
chmod 600 "/home/${GUEST_USER}/.ssh/authorized_keys"
passwd -l "$GUEST_USER"  # disable password login

# 5. SSH hardening for guest user only
cat > "$SSHD_DROPIN" <<'EOF'
# Restrict guest agent account: shell access only, no tunneling
Match User guestagent
    AllowTcpForwarding no
    X11Forwarding no
    PermitTunnel no
    GatewayPorts no
    AllowAgentForwarding no
    PermitTTY yes
EOF

# 6. Validate sshd config and reload
sshd -t
systemctl reload ssh

echo "OK: ${GUEST_USER} provisioned. Test with:"
echo "  ssh -i <guest-priv-key> ${GUEST_USER}@$(hostname)"
echo "Guest can rw: $PROJECT_DIR"
echo "Guest cannot: sudo, ls /home/${OPERATOR_HOST_USER}, port-forward, agent-forward"
