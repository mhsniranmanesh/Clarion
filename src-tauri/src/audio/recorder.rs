use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::SampleFormat;
use hound::{WavSpec, WavWriter};
use serde::{Deserialize, Serialize};
use std::io::Cursor;
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

const TARGET_SAMPLE_RATE: u32 = 16000;
const TARGET_CHANNELS: u16 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioDevice {
    pub name: String,
    pub is_default: bool,
}

/// List all available audio input devices.
pub fn list_input_devices() -> Vec<AudioDevice> {
    let host = cpal::default_host();
    let default_name = host
        .default_input_device()
        .and_then(|d| d.name().ok())
        .unwrap_or_default();

    host.input_devices()
        .map(|devices| {
            devices
                .filter_map(|d| {
                    let name = d.name().ok()?;
                    Some(AudioDevice {
                        is_default: name == default_name,
                        name,
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

enum RecorderCommand {
    Stop,
}

/// Handle to a recording session running on a dedicated thread.
/// This is Send + Sync because it only holds a channel sender and shared sample buffer.
pub struct RecordingHandle {
    cmd_tx: mpsc::Sender<RecorderCommand>,
    result_rx: mpsc::Receiver<Result<Vec<u8>, String>>,
}

impl RecordingHandle {
    /// Stop recording and get the WAV data.
    pub fn stop(self) -> Result<Vec<u8>, String> {
        let _ = self.cmd_tx.send(RecorderCommand::Stop);
        self.result_rx
            .recv()
            .unwrap_or_else(|e| Err(format!("Recording thread disconnected: {e}")))
    }
}

/// Start recording on a dedicated thread. Returns a handle to stop it.
/// If `device_name` is Some, uses that specific device; otherwise uses the system default.
pub fn start_recording(device_name: Option<String>) -> Result<RecordingHandle, String> {
    let (cmd_tx, cmd_rx) = mpsc::channel();
    let (result_tx, result_rx) = mpsc::channel();

    // Spawn a dedicated thread for audio capture (cpal::Stream is !Send)
    thread::spawn(move || {
        let result = run_recording(cmd_rx, device_name);
        let _ = result_tx.send(result);
    });

    // Wait briefly to check if the thread started OK
    // (errors would come back immediately via result_rx)
    thread::sleep(std::time::Duration::from_millis(100));

    Ok(RecordingHandle { cmd_tx, result_rx })
}

fn run_recording(
    cmd_rx: mpsc::Receiver<RecorderCommand>,
    device_name: Option<String>,
) -> Result<Vec<u8>, String> {
    let host = cpal::default_host();
    let device = match &device_name {
        Some(name) => host
            .input_devices()
            .map_err(|e| format!("Failed to list devices: {e}"))?
            .find(|d| d.name().ok().as_deref() == Some(name.as_str()))
            .ok_or_else(|| format!("Audio device '{}' not found", name))?,
        None => host
            .default_input_device()
            .ok_or("No input device available")?,
    };

    log::info!("Using input device: {}", device.name().unwrap_or_default());

    let config = device
        .default_input_config()
        .map_err(|e| format!("Failed to get input config: {e}"))?;

    let device_sample_rate = config.sample_rate().0;
    let device_channels = config.channels();

    log::info!(
        "Recording at {}Hz, {} channels",
        device_sample_rate,
        device_channels
    );

    let samples: Arc<Mutex<Vec<f32>>> = Arc::new(Mutex::new(Vec::new()));
    let channels = device_channels as usize;
    let err_fn = |err| log::error!("Audio stream error: {err}");

    let stream = match config.sample_format() {
        SampleFormat::F32 => {
            let samples = samples.clone();
            device
                .build_input_stream(
                    &config.into(),
                    move |data: &[f32], _| {
                        let mono: Vec<f32> = data
                            .chunks(channels)
                            .map(|frame| frame.iter().sum::<f32>() / channels as f32)
                            .collect();
                        samples.lock().unwrap().extend_from_slice(&mono);
                    },
                    err_fn,
                    None,
                )
                .map_err(|e| format!("Failed to build stream: {e}"))?
        }
        SampleFormat::I16 => {
            let samples = samples.clone();
            device
                .build_input_stream(
                    &config.into(),
                    move |data: &[i16], _| {
                        let mono: Vec<f32> = data
                            .chunks(channels)
                            .map(|frame| {
                                frame.iter().map(|&s| s as f32 / 32768.0).sum::<f32>()
                                    / channels as f32
                            })
                            .collect();
                        samples.lock().unwrap().extend_from_slice(&mono);
                    },
                    err_fn,
                    None,
                )
                .map_err(|e| format!("Failed to build stream: {e}"))?
        }
        format => return Err(format!("Unsupported sample format: {format:?}")),
    };

    stream
        .play()
        .map_err(|e| format!("Failed to play stream: {e}"))?;

    log::info!("Recording started");

    // Block until we receive Stop command
    let _ = cmd_rx.recv();

    // Drop stream to stop recording
    drop(stream);
    log::info!("Recording stopped");

    let samples = samples.lock().unwrap();
    if samples.is_empty() {
        return Err("No audio recorded".to_string());
    }

    log::info!(
        "Captured {} samples at {}Hz",
        samples.len(),
        device_sample_rate
    );

    // Resample to 16kHz mono if needed
    let resampled = if device_sample_rate != TARGET_SAMPLE_RATE {
        resample(&samples, device_sample_rate, TARGET_SAMPLE_RATE)
    } else {
        samples.to_vec()
    };

    encode_wav(&resampled, TARGET_SAMPLE_RATE, TARGET_CHANNELS)
}

fn resample(samples: &[f32], from_rate: u32, to_rate: u32) -> Vec<f32> {
    let ratio = from_rate as f64 / to_rate as f64;
    let output_len = (samples.len() as f64 / ratio) as usize;
    let mut output = Vec::with_capacity(output_len);

    for i in 0..output_len {
        let src_pos = i as f64 * ratio;
        let idx = src_pos as usize;
        let frac = src_pos - idx as f64;

        let sample = if idx + 1 < samples.len() {
            samples[idx] * (1.0 - frac as f32) + samples[idx + 1] * frac as f32
        } else {
            samples[idx]
        };
        output.push(sample);
    }

    output
}

fn encode_wav(samples: &[f32], sample_rate: u32, channels: u16) -> Result<Vec<u8>, String> {
    let spec = WavSpec {
        channels,
        sample_rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };

    let mut buffer = Cursor::new(Vec::new());
    {
        let mut writer =
            WavWriter::new(&mut buffer, spec).map_err(|e| format!("WAV writer error: {e}"))?;
        for &sample in samples {
            let clamped = sample.clamp(-1.0, 1.0);
            let int_sample = (clamped * 32767.0) as i16;
            writer
                .write_sample(int_sample)
                .map_err(|e| format!("WAV write error: {e}"))?;
        }
        writer
            .finalize()
            .map_err(|e| format!("WAV finalize error: {e}"))?;
    }

    Ok(buffer.into_inner())
}
