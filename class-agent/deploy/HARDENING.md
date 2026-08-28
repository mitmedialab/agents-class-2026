# Host hardening

The host currently has no `~/.ssh/authorized_keys`, so do not disable SSH password
authentication until a client public key has been installed and tested in a second session.

Install the safe SSH baseline and firewall:

```bash
sudo install -m 0644 deploy/60-class-agent-sshd.conf /etc/ssh/sshd_config.d/60-class-agent.conf
sudo sshd -t
sudo systemctl reload ssh

sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

After installing and testing a public key in a separate terminal, add
`PasswordAuthentication no` to the SSH snippet, validate with `sudo sshd -t`, and reload SSH.
