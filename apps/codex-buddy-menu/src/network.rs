use std::{
    net::{IpAddr, Ipv4Addr, UdpSocket},
    process::Command,
};

pub fn lan_ip_text() -> String {
    lan_ip()
        .map(|ip| ip.to_string())
        .unwrap_or_else(|| "unknown".to_string())
}

fn lan_ip() -> Option<Ipv4Addr> {
    for interface in ["en0", "en1", "en2"] {
        if let Some(ip) = interface_ipv4(interface) {
            return Some(ip);
        }
    }

    let socket = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0)).ok()?;
    socket.connect((Ipv4Addr::new(8, 8, 8, 8), 80)).ok()?;
    match socket.local_addr().ok()?.ip() {
        IpAddr::V4(ip) if !ip.is_loopback() && !ip.is_unspecified() => Some(ip),
        _ => None,
    }
}

fn interface_ipv4(interface: &str) -> Option<Ipv4Addr> {
    let output = Command::new("/usr/sbin/ipconfig")
        .args(["getifaddr", interface])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let ip = text.trim().parse::<Ipv4Addr>().ok()?;
    if ip.is_loopback() || ip.is_unspecified() {
        None
    } else {
        Some(ip)
    }
}
