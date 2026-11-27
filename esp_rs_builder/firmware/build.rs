// The linker script (`-Tlinkall.x`) is passed via .cargo/config.toml rustflags (passing it here too defines RAM twice).
// OTA partition setup arrives with task 05+.
fn main() {
    println!("cargo:rerun-if-changed=build.rs");
}
