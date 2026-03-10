import os
import json
import tempfile
import subprocess
import shutil
import re
import logging
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

SUBTITLE_STYLES = {
    'tiktok_bold': {
        'FontName': 'Arial Black',
        'FontSize': 24,
        'PrimaryColour': '&H00FFFFFF',
        'OutlineColour': '&H00000000',
        'Outline': 3,
        'Bold': 1,
        'Shadow': 0,
        'Alignment': 2,
        'MarginV': 50,
    },
    'clean': {
        'FontName': 'Arial',
        'FontSize': 20,
        'PrimaryColour': '&H00FFFFFF',
        'OutlineColour': '&H00000000',
        'Outline': 1,
        'Bold': 0,
        'Shadow': 1,
        'Alignment': 2,
        'MarginV': 40,
    },
    'impacto': {
        'FontName': 'Impact',
        'FontSize': 28,
        'PrimaryColour': '&H00FFFFFF',
        'OutlineColour': '&H00000000',
        'Outline': 3,
        'Bold': 1,
        'Shadow': 0,
        'Alignment': 5,
        'MarginV': 0,
    },
    'minimalista': {
        'FontName': 'Arial',
        'FontSize': 16,
        'PrimaryColour': '&H00FFFFFF',
        'OutlineColour': '&H80000000',
        'Outline': 1,
        'Bold': 0,
        'Shadow': 0,
        'Alignment': 2,
        'MarginV': 30,
    },
    'karaoke': {
        'FontName': 'Arial Black',
        'FontSize': 22,
        'PrimaryColour': '&H00FFFFFF',
        'OutlineColour': '&H00000000',
        'Outline': 2,
        'Bold': 1,
        'Shadow': 0,
        'Alignment': 2,
        'MarginV': 50,
    },
}


def get_video_duration(video_path):
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_streams', video_path],
        capture_output=True, text=True
    )
    try:
        data = json.loads(result.stdout)
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                dur = float(stream.get('duration', 0))
                if dur > 0:
                    return dur
    except Exception:
        pass
    return 60.0


def hex_to_ass_color(hex_color):
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return '&H00{:02X}{:02X}{:02X}'.format(b, g, r)


def text_to_srt(text, duration, srt_path):
    parts = re.split(r'(?<=[.!?])\s+|(?<=,)\s+', text.strip())
    parts = [p.strip() for p in parts if p.strip()]
    chunks = []
    for part in parts:
        words = part.split()
        for i in range(0, max(len(words), 1), 8):
            chunk = ' '.join(words[i:i + 8])
            if chunk:
                chunks.append(chunk)
    if not chunks:
        chunks = [text.strip()]
    chunk_dur = duration / len(chunks)

    def fmt(secs):
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        ms = int((secs % 1) * 1000)
        return '{:02d}:{:02d}:{:02d},{:03d}'.format(h, m, s, ms)

    with open(srt_path, 'w', encoding='utf-8') as f:
        for i, chunk in enumerate(chunks):
            start = i * chunk_dur
            end = start + chunk_dur - 0.05
            f.write('{}\n{} --> {}\n{}\n\n'.format(i + 1, fmt(start), fmt(end), chunk))


def build_force_style(style_name, position, color_hex):
    style = SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES['tiktok_bold']).copy()
    pos_map = {'top': 8, 'center': 5, 'bottom': 2}
    style['Alignment'] = pos_map.get(position, 2)
    if position == 'top':
        style['MarginV'] = 50
    elif position == 'center':
        style['MarginV'] = 0
    if color_hex and color_hex.startswith('#') and color_hex != '#FFFFFF':
        style['PrimaryColour'] = hex_to_ass_color(color_hex)
    return ','.join('{}={}'.format(k, v) for k, v in style.items())


def burn_subtitles(input_path, srt_path, output_path, style_name, position, color_hex):
    force_style = build_force_style(style_name, position, color_hex)
    escaped = srt_path.replace('\\', '/').replace(':', '\\:')
    cmd = [
        'ffmpeg', '-i', input_path,
        '-vf', "subtitles='{}':force_style='{}'".format(escaped, force_style),
        '-c:a', 'copy',
        '-preset', 'fast',
        '-y', output_path
    ]
    logging.info('Running FFmpeg: %s', ' '.join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        logging.error('FFmpeg stderr: %s', result.stderr[-1000:])
        raise RuntimeError('FFmpeg failed: {}'.format(result.stderr[-500:]))


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'genius-ffmpeg'})


@app.route('/process-video', methods=['POST'])
def process_video():
    if 'video' not in request.files:
        return jsonify({'error': 'Missing video file in multipart body'}), 400
    video_file = request.files['video']
    config_raw = request.form.get('config', '{}')
    try:
        config = json.loads(config_raw)
    except json.JSONDecodeError:
        return jsonify({'error': 'Invalid JSON in config field'}), 400
    subtitles = config.get('subtitles', {})
    sub_enabled = subtitles.get('enabled', False)
    sub_text = subtitles.get('text', '').strip()
    sub_style = subtitles.get('style', 'tiktok_bold')
    sub_position = subtitles.get('position', 'bottom')
    sub_color = subtitles.get('color', '#FFFFFF')
    tmpdir = tempfile.mkdtemp()
    try:
        input_path = os.path.join(tmpdir, 'input.mp4')
        output_path = os.path.join(tmpdir, 'output.mp4')
        srt_path = os.path.join(tmpdir, 'subtitles.srt')
        video_file.save(input_path)
        logging.info('Video saved to %s', input_path)
        if sub_enabled and sub_text:
            duration = get_video_duration(input_path)
            logging.info('Video duration: %.2fs', duration)
            text_to_srt(sub_text, duration, srt_path)
            logging.info('SRT generated at %s', srt_path)
            burn_subtitles(input_path, srt_path, output_path, sub_style, sub_position, sub_color)
            logging.info('Subtitles burned successfully')
        else:
            shutil.copy(input_path, output_path)
            logging.info('No subtitles - copied original')
        return send_file(
            output_path,
            mimetype='video/mp4',
            as_attachment=True,
            download_name='processed.mp4',
        )
    except Exception as exc:
        logging.exception('Error processing video')
        return jsonify({'error': str(exc)}), 500
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
