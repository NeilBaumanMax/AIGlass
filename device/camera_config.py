"""Build a video-only RKIPC profile from the board's IMX415 factory INI."""
import argparse
import configparser
from pathlib import Path


def configure(source, target):
    config = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(';', '#'))
    config.read(source, encoding='utf-8')
    required = ('audio.0', 'video.source', 'video.0', 'isp.0.adjustment')
    if any(section not in config for section in required):
        raise ValueError('Incomplete RKIPC factory configuration')
    changes = {
        'audio.0': {'enable': '0', 'enable_vqe': '0'},
        'video.source': {'enable_aiq': '1', 'enable_rtsp': '1', 'enable_rtmp': '0',
                         'enable_vo': '0', 'enable_ivs': '0', 'enable_npu': '0',
                         'enable_jpeg': '0', 'enable_venc_0': '1',
                         'enable_venc_1': '0', 'enable_venc_2': '0'},
        'video.0': {'width': '1280', 'height': '720', 'max_width': '1280', 'max_height': '720',
                    'video_type': 'videoStream', 'output_data_type': 'H.264',
                    'src_frame_rate_num': '15', 'src_frame_rate_den': '1',
                    'dst_frame_rate_num': '15', 'dst_frame_rate_den': '1',
                    'gop': '15', 'rc_mode': 'CBR', 'mid_rate': '1500', 'max_rate': '1500',
                    'buffer_size': '1382400', 'enable_motion_deblur': '0'},
        'isp.0.adjustment': {'fps': '15'},
        'osd.common': {'enable_osd': '0'},
        **{'storage.' + str(i): {'enable': '0'} for i in range(3)},
    }
    for section, values in changes.items():
        if not config.has_section(section):
            config.add_section(section)
        config[section].update(values)
    # Keep the sensor's factory IQ, IR-cut and exposure settings. Write to our
    # own profile: the vendor boot script overwrites /userdata/rkipc.ini.
    output = Path(target)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', encoding='utf-8', newline='\n') as stream:
        config.write(stream)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    if args.source.resolve() == args.target.resolve():
        parser.error('Use a separate output file; preserve the original profile')
    configure(args.source, args.target)
