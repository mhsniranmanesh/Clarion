use arboard::Clipboard;

pub fn copy_and_paste(text: &str) -> Result<(), String> {
    // Step 1: Copy to clipboard
    let mut clipboard =
        Clipboard::new().map_err(|e| format!("Failed to access clipboard: {e}"))?;
    clipboard
        .set_text(text)
        .map_err(|e| format!("Failed to set clipboard: {e}"))?;

    log::info!("Text copied to clipboard ({} chars)", text.len());

    // Step 2: Small delay to ensure clipboard is set before simulating paste
    std::thread::sleep(std::time::Duration::from_millis(50));

    // Step 3: Simulate Cmd+V / Ctrl+V
    if let Err(e) = simulate_paste() {
        log::warn!("Paste simulation failed (clipboard still has the text): {e}");
    }

    Ok(())
}

pub fn copy_only(text: &str) -> Result<(), String> {
    let mut clipboard =
        Clipboard::new().map_err(|e| format!("Failed to access clipboard: {e}"))?;
    clipboard
        .set_text(text)
        .map_err(|e| format!("Failed to set clipboard: {e}"))?;
    log::info!("Text copied to clipboard ({} chars)", text.len());
    Ok(())
}

fn simulate_paste() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        // Use osascript instead of enigo — avoids the Accessibility permission
        // abort trap that crashes the app. osascript inherits permissions from
        // the parent process (e.g. iTerm) and works reliably.
        let status = std::process::Command::new("osascript")
            .arg("-e")
            .arg(r#"tell application "System Events" to keystroke "v" using command down"#)
            .status()
            .map_err(|e| format!("Failed to run osascript: {e}"))?;

        if !status.success() {
            return Err(format!("osascript exited with status: {status}"));
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        use enigo::{Enigo, Key, Keyboard, Settings};

        let mut enigo =
            Enigo::new(&Settings::default()).map_err(|e| format!("Failed to init enigo: {e}"))?;
        enigo
            .key(Key::Control, enigo::Direction::Press)
            .map_err(|e| format!("Key press failed: {e}"))?;
        enigo
            .key(Key::Unicode('v'), enigo::Direction::Click)
            .map_err(|e| format!("Key click failed: {e}"))?;
        enigo
            .key(Key::Control, enigo::Direction::Release)
            .map_err(|e| format!("Key release failed: {e}"))?;
    }

    log::info!("Simulated paste keystroke");
    Ok(())
}
