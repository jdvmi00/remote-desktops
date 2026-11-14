//! Embed the Python host helpers so an installed binary never runs helper code
//! from the checkout it was built in.
use std::{env, fs, path::Path};

fn collect(root: &Path, directory: &Path, files: &mut Vec<String>) {
    let mut entries: Vec<_> = fs::read_dir(directory)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .collect();
    entries.sort();
    for path in entries {
        let name = path.file_name().unwrap().to_string_lossy().into_owned();
        if path.is_dir() {
            if name != "__pycache__" {
                collect(root, &path, files);
            }
        } else if [".py", ".ps1", ".cs"]
            .iter()
            .any(|kind| name.ends_with(kind))
        {
            // Helper sources only: never a stray editor or tool file.
            let relative = path.strip_prefix(root).unwrap();
            files.push(relative.to_string_lossy().replace('\\', "/"));
        }
    }
}

fn main() {
    let root = env::var("CARGO_MANIFEST_DIR").unwrap();
    let root = Path::new(&root);
    println!("cargo:rerun-if-changed=remote_desktops");
    println!("cargo:rerun-if-changed=build.rs");
    let mut files = Vec::new();
    collect(root, &root.join("remote_desktops"), &mut files);
    // FNV-1a over names and contents: the snapshot directory is named after it,
    // so two builds with different helpers never share one.
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    let mut feed = |bytes: &[u8]| {
        for byte in bytes {
            hash ^= u64::from(*byte);
            hash = hash.wrapping_mul(0x0100_0000_01b3);
        }
    };
    let mut table = String::new();
    for name in &files {
        let path = root.join(name);
        feed(name.as_bytes());
        feed(&[0]);
        feed(&fs::read(&path).unwrap());
        feed(&[0]);
        table.push_str(&format!("    ({name:?}, include_bytes!({path:?})),\n"));
    }
    let source = format!(
        "pub const ID: &str = \"{hash:016x}\";\npub const FILES: &[(&str, &[u8])] = &[\n{table}];\n"
    );
    let out = env::var("OUT_DIR").unwrap();
    fs::write(Path::new(&out).join("helpers.rs"), source).unwrap();
}
