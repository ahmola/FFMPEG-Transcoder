import sys
import subprocess
import av
import requests
import base64
import io
from logger import logger

"""
Obviously need to be fixed, because this was built for communication with the legacy code which doesn't care about the REST
"""
MP4_DUMP_PATH = "C:/Bento4-SDK-1-6-0-641.x86_64-microsoft-win32/bin/mp4dump.exe"

frame_type_map = {
        1 : 'I-Frame',
        2 : 'P-Frame',
        3 : 'B-Frame',
}

packet_info = ",".join([
    "pos",                 # 파일 내 오프셋
    "pts_time","dts_time", # PTS/DTS(초)
    "duration_time",       # 패킷 지속시간(초)  ← 주의: packet은 duration_time
    "size","flags"         # 바이트 크기, 키플래그 등
])

frame_info = ",".join([
    "coded_picture_number",
    "display_picture_number", # 디코딩 순서 프레임 번호
    "pict_type","key_frame", # 표시 순서 프레임 번호
    "pkt_pts_time","pkt_dts_time", # I/P/B, 키프레임
    "best_effort_timestamp_time", # PTS/DTS(초)
    "pkt_duration_time", # PTS 없을 때 보정
    "pkt_pos","pkt_pts_time","pkt_size", # 프레임 지속시간(초)
    "interlaced_frame","top_field_first","repeat_pict", # 파일 내 오프셋
    "side_data_list" # HDR 등 프레임 메타
])

args_ffprobe = [
    "ffprobe", "-v", "error", "-print_format", "json",
    "-show_entries",
    "format=filename,format_name,format_long_name,nb_streams,duration,size,bit_rate:"
    "format_tags=major_brand,minor_version,compatible_brands:"
    "stream=index,codec_type,codec_name,codec_tag_string,profile,level,pix_fmt,width,height,field_order,avg_frame_rate,side_data_list,extradata_size",
    "video.mp4"
]

def ffmpeg_remux():
    logger.info("Processing ffmpeg remux")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", "video.mp4",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v", "libx264", "-profile:v", "main", "-level", "4.0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-tag:v", "avc1",
        "video_remux.mp4"
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0

def ffmpeg_transcode():
    logger.info("Processing ffmpeg transcode")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", "video.mp4",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest",
        "-c:v", "libx264", "-profile:v", "main", "-level", "4.0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-tag:v", "avc1",
        "video_transcode.mp4"
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr}")

def request_login(api_url:str):
    # api header
    login_header = {
        "x-account-id": "admin",
        "x-account-pass": "admin",
        "x-account-group": "group1",
        "x-license": "licAccessControl"
    }

    # api param
    login_param = {
        "force-login": True
    }

    # url 초기화
    login_url = api_url + "/api/login"
    logger.info(f"Request Login Get Request to {login_url}")

    # 요청을 보냄
    login_response = requests.get(url=login_url, headers=login_header, params=login_param).json().get("results")
    logger.info(f"Login Response Result {login_response}")

    # 필요한 정보 추출
    token = login_response.get("auth_token")
    api_serial = str(login_response.get("api_serial"))
    user_serial = str(login_response.get("user_serial"))
    ctx_serial = str(0)

    return token, api_serial, user_serial, ctx_serial

def request_device_list(api_url:str, token:str, api_serial:str, user_serial:str, ctx_serial:str):
    # api header
    device_list_request_header = {
        "x-auth-token": token,
        "x-api-serial": api_serial
    }
    # api param
    device_list_request_param = {
        "auth-token": token,
        "api-serial": api_serial,
        "user-serial": user_serial,
        "ctx-serial": ctx_serial
    }

    # url
    device_list_url = api_url + f"/api/device/list/{user_serial}/{ctx_serial}"
    logger.info(f"Request Device List Get Request to {device_list_url}")

    # device 리스트 추출
    device_list_response = requests.get(device_list_url, headers=device_list_request_header,
                                        params=device_list_request_param).json().get("results").get("tree")
    logger.info(f"Device List Response Result {device_list_response}")

    # device들의 dev_serial을 추출
    dev_serial_list = [device.get("dev_serial") for device in device_list_response]

    return dev_serial_list

def request_video(api_url:str, from_date:str, to_date:str, token:str, api_serial:str, dev_serial_list):
    # api param
    mp4_request_param = {
        "from_date": from_date,
        "to_date": to_date,
    }

    # api header
    mp4_request_header = {
        "x-auth-token": token,
        "x-api-serial": api_serial
    }

    # url 초기화
    mp4_request_uri = api_url + f"/api/video/download/{dev_serial_list[-1]}/0"
    logger.info(f"Request MP4 Get Request to {mp4_request_uri}")

    # 요청 전송
    mp4_response = requests.get(mp4_request_uri, headers=mp4_request_header, params=mp4_request_param, stream=True)
    mp4_response.raise_for_status()
    logger.info(f"Headers : {mp4_response.headers}, {mp4_response.history}")

    # base64 데이터, 문자열 저장, 디코더를 통해 영상 변환 가능
    mp4_base64_text = base64.b64encode(mp4_response.content).decode("utf-8")
    mp4_raw_data = io.BytesIO(mp4_response.content)

    # base64 문자열 저장, 해당 파일의 텍스트를 복사하여 bas64.guru에서 디코딩하면 영상 확인 가능
    with open("video.txt", "w") as f:
        f.write(mp4_base64_text)

    # 원본 mp4 저장
    logger.info(f"Process MP4 Repackaging to WMP")
    with open("video.mp4", "wb") as f:
        for chunk in mp4_response.iter_content(1024):
            if chunk:
                f.write(chunk)

    # 윈도우에서도 재생가능한 형식으로 맞춤, 리먹스 -> 실패하면 트랜스코드
    if not ffmpeg_remux():
        ffmpeg_transcode()

    # 바이트 데이터 반환
    return mp4_raw_data

def analyze_video(raw_data:io.BytesIO):
    try:
        # 바이트 데이터를 읽어들임
        container = av.open(raw_data)
        logger.info(f"Reading Frame Info from mp4 {container.format.name}, start : {container.start_time}, bit rate : {container.bit_rate} bps")

        iframe_count = 0
        print("--------------------------------------------------")
        # 모든 비디오 스트림을 순회하며 프레임 정보를 출력
        for frame in container.decode(video=0):
            # I-Frame : 1, P-Frame : 2, B-Frame : 3
            frame_type = frame_type_map.get(frame.pict_type)
            logger.info(f"Frame Number: {frame.pts}")
            logger.info(f"Frame Type: {frame_type}")
            logger.info(f"Frame Time: {frame.duration}")

            # I-Frame의 개수를 셈
            if frame.key_frame:
                iframe_count += 1

            # Frame의 기본 데이터 외에, 서버(Vurix)에서 추가적으로 프레임에 저장되어 있는 데이터가 있는지 확인
            if frame.side_data:
                logger.info(f"Frame Side Data: {frame.side_data}")
                for side_data in frame.side_data:
                    logger.info(f"  Type: {side_data.type.name}")
                    logger.info(f"  Data: {side_data.as_dict()}")

            print("--------------------------------------------------")

        logger.info(f"Total I-Frame : {iframe_count}\n")

        # 파일 정보 메타데이터
        ffprobe_out = subprocess.check_output(args_ffprobe, text=True)
        open("headers.json", "w", encoding="utf-8").write(ffprobe_out)
        logger.info(f"FFProbe created headers.json")

        # 어떻게 재생할 지를 담은 메타데이터
        proc = subprocess.run(
            [MP4_DUMP_PATH, "--format", "json", "video.mp4"],
            capture_output=True, text=True
        )
        open("boxes.json", "w", encoding="utf-8").write(proc.stdout or "")
        logger.info(f"MP4Dump created boxes.json")

        if proc.stderr:
            logger.error(f"MP4Dump error: {proc.stderr}")
            open("mp4dump_error.log", "w", encoding="utf-8").write(proc.stderr)
        logger.info("returncode:%s", proc.returncode)

        open("frames.json", "w", encoding="utf-8").write(
            subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames", "-show_entries",
                f"frame={frame_info}",
                "-of", "json", "video.mp4"
            ], text=True)
        )
        logger.info(f"Frame Info created frames.json")

        open("packets.json", "w", encoding="utf-8").write(
            subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_packets", "-show_entries",
                f"frame={packet_info}",
                "-of", "json", "video.mp4"
            ], text=True)
        )
        logger.info(f"Packet Info created packets.json")

        # 프레임을 다른 서버로 전송
        for frame in container.demux(stream):
            h264_bytes = bytes(frame)
            logger.info(f"Frame H.264 Bytes : {h264_bytes}")

            packet = build_packet(channel_id, h264_bytes, True)
            logger.info(f"Packet Ready : {packet}")

            s.sendall(packet)

    except av.PyAVCallbackError as e:
        logger.error(f"Cannot open or decode. mp4 maybe damaged : {e}")
    except FileNotFoundError:
        logger.error("Cannot find mp4. Check the path")


def receive_video(api_url: str):
    # 로그인 및 토큰 발급
    token, api_serial, user_serial, ctx_serial = request_login(api_url)

    # 장비 목록 조회 GET 요청
    dev_serial_list = request_device_list(api_url, token, api_serial, user_serial, ctx_serial)

    # 영상 다운로드 GET요청
    mp4_raw_data = request_video(api_url, "202508251721", "202508251725", token, api_serial, dev_serial_list)

    # av 모듈로 프레임 메타 데이터 추출
    analyze_video(mp4_raw_data)

    return mp4_raw_data

if __name__ == '__main__':
    api_url, tcp_socket_url = "", ""

    if len(sys.argv) != 2:
        logger.error("Need to specify two IP Addresses.")
        logger.error("First is for the Rest API, Second is for the Socket")
        logger.error("e.g. python test_api.py http://[url1]:[port] [url2]:[port]")
        logger.info("Instead, default url will be used")

        api_url = "enter api url"
        tcp_socket_url = "enter socket url"
    else:
        api_url = sys.argv[1]
        tcp_socket_url = sys.argv[2]

    logger.info(f"API Url: {api_url}, tcp_socket_url: {tcp_socket_url}")

    # 영상 파일 데이터 받음
    mp4_raw_data = receive_video(api_url)
