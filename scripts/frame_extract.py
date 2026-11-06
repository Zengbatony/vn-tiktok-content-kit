#!/usr/bin/env python3
# frame_extract.py — 竞品视频抽帧工具（vn-tiktok-content-kit 自带）
#
# 用法：
#   python scripts/frame_extract.py --videos-dir videos --out frames
#   python scripts/frame_extract.py --videos-dir videos --out frames --short-n 12 --long-step 12 --max-n 40
#
# 做什么：
#   1) 对 videos-dir 下每个 mp4，按时间轴均匀抽帧（短视频 12 帧；长视频每 ~12s 一帧，封顶 40）
#   2) 拼 5×N 蒙太奇（缩到可读分辨率，避免视觉工具因过大拒读）
#   3) 额外抽 钩子(1s)/中段/收尾 三张高清特写，供视觉读屏
#
# 依赖：ffmpeg（系统 PATH）+ Python 标准库。无第三方依赖。
import subprocess, os, glob, argparse

def ffprobe_dur(path):
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                   'format=duration', '-of',
                                   'default=noprint_wrappers=1:nokey=1', path])
    return float(out.strip())

def run(cmd):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

def main():
    ap = argparse.ArgumentParser(description='竞品视频抽帧：均匀帧 + 蒙太奇 + 钩子/中段/收尾特写')
    ap.add_argument('--videos-dir', default='videos', help='含 mp4 的目录（默认 ./videos）')
    ap.add_argument('--out', default=None, help='输出根目录（默认 <videos-dir>/frames）')
    ap.add_argument('--short-n', type=int, default=12, help='短视频(<90s)抽帧数（默认 12）')
    ap.add_argument('--long-step', type=float, default=12.0, help='长视频每 N 秒一帧（默认 12）')
    ap.add_argument('--max-n', type=int, default=40, help='单视频抽帧上限（默认 40）')
    args = ap.parse_args()

    vdir = os.path.abspath(args.videos_dir)
    fdir = os.path.abspath(args.out) if args.out else os.path.join(vdir, 'frames')
    os.makedirs(fdir, exist_ok=True)

    mp4s = sorted(glob.glob(os.path.join(vdir, '*.mp4')))
    if not mp4s:
        print(f'在 {vdir} 下没找到 mp4'); return

    for mp4 in mp4s:
        vid = os.path.splitext(os.path.basename(mp4))[0]
        od = os.path.join(fdir, vid)
        os.makedirs(od, exist_ok=True)
        try:
            D = ffprobe_dur(mp4)
        except Exception as e:
            print('skip', vid, e); continue

        # 帧数：短视频固定 short-n；长视频按步长，封顶 max-n，下限 short-n
        if D <= 90:
            N = args.short_n
        else:
            N = max(args.short_n, min(args.max_n, round(D / args.long_step)))
        cols = 5 if N > 20 else 4
        rows = (N + cols - 1) // cols
        print(f'{vid}  dur={D:.1f}s  frames={N} tile={cols}x{rows}')

        frames = []
        for i in range(1, N + 1):
            t = D * i / (N + 1)
            f = os.path.join(od, f't{i:02d}.jpg')
            run(['ffmpeg', '-y', '-ss', f'{t:.2f}', '-i', mp4, '-vf', 'scale=240:-1',
                 '-frames:v', '1', '-q:v', '5', f])
            frames.append(f)

        mont = os.path.join(od, 'montage.jpg')
        run(['ffmpeg', '-y', '-i', os.path.join(od, 't%02d.jpg'), '-filter_complex',
             f'tile={cols}x{rows}', '-frames:v', '1', mont])

        for label, t in [('hook', min(1.0, D * 0.1)), ('mid', D / 2),
                         ('cta', max(D - 1.5, D * 0.85))]:
            f = os.path.join(od, f'{label}.jpg')
            run(['ffmpeg', '-y', '-ss', f'{t:.2f}', '-i', mp4, '-frames:v', '1', '-q:v', '2', f])
        print(f'  -> {len(frames)} 帧 + montage + 3 特写 已存 {od}')

    print('DONE')

if __name__ == '__main__':
    main()
