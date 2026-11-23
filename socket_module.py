import socket
import threading
import time
import json
import csv
import os
from datetime import datetime
import pandas as pd
from tcp_algorithm import TCPCongestionControlSimulator


class PacketSocketCommunicator:
    """ Python socket 기반 송수신자 간 기본 패킷 전송 및 덤프 모듈"""

    def __init__(self, host="127.0.0.1", port=9999):
        self.host = host
        self.port = port
        self.packet_dumps = []  # 패킷 덤프 기록 리스트
        self._stop_event = threading.Event()
        self._rx_thread = None

    def _record_dump(self, direction, pkt_type, seq, payload_info=""):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {direction} | {pkt_type} | SEQ={seq} | {payload_info}"
        self.packet_dumps.append(log_entry)

    def _receiver_loop(self, rtt_ms):
        """수신자(Receiver) 소켓 스레드: 패킷을 받고 ACK를 회신"""
        rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx_sock.bind((self.host, self.port))
        rx_sock.settimeout(0.2)

        while not self._stop_event.is_set():
            try:
                raw_data, sender_addr = rx_sock.recvfrom(1024)
                packet = json.loads(raw_data.decode("utf-8"))
                seq = packet.get("seq", 0)

                self._record_dump("RECV (RX)", "DATA", seq, f"from {sender_addr[0]}:{sender_addr[1]}")

                # RTT 지연 반영 (편도 지연)
                if rtt_ms > 0:
                    time.sleep((rtt_ms / 1000.0) / 2.0)

                # ACK 패킷 생성 및 회신
                ack_packet = json.dumps({"type": "ACK", "ack": seq + 1}).encode("utf-8")
                rx_sock.sendto(ack_packet, sender_addr)
                self._record_dump("SEND (RX)", "ACK", seq + 1, "ACK 회신 완료")

            except socket.timeout:
                continue
            except Exception:
                break

        rx_sock.close()

    def start_receiver(self, rtt_ms=100):
        self._stop_event.clear()
        self._rx_thread = threading.Thread(
            target=self._receiver_loop, args=(rtt_ms,), daemon=True
        )
        self._rx_thread.start()
        time.sleep(0.05)  # 수신자 소켓 바인딩 대기

    def stop_receiver(self):
        self._stop_event.set()
        if self._rx_thread:
            self._rx_thread.join(timeout=0.5)

    def send_packets(self, start_seq, count, rtt_ms=100):
        """송신자(Sender) 소켓: 현재 Cwnd 개수만큼 패킷을 소켓으로 전송하고 ACK 수신"""
        tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx_sock.settimeout(max(0.5, (rtt_ms / 1000.0) * 2))

        try:
            for i in range(count):
                seq = start_seq + i
                payload = json.dumps({"type": "DATA", "seq": seq}).encode("utf-8")
                tx_sock.sendto(payload, (self.host, self.port))
                self._record_dump("SEND (TX)", "DATA", seq, f"to {self.host}:{self.port}")

                try:
                    ack_raw, _ = tx_sock.recvfrom(1024)
                    ack_data = json.loads(ack_raw.decode("utf-8"))
                    self._record_dump("RECV (TX)", "ACK", ack_data.get("ack"), "ACK 수신 확인")
                except socket.timeout:
                    self._record_dump("TIMEOUT (TX)", "ERR", seq, "ACK 응답 시간 초과")
        finally:
            tx_sock.close()

    def save_dump_log(self, filepath="packet_dump.log"):
        """패킷 덤프 내역을 .log 파일로 저장"""
        with open(filepath, "w", encoding="utf-8") as f:
            for line in self.packet_dumps:
                f.write(line + "\n")
        return filepath


class CwndDataCollectorAndAnalyzer:
    """ 알고리즘별 Cwnd 변화 데이터(CSV/로그) 자동 수집 및 데이터 분석 모듈"""

    def __init__(self):
        self.records = []

    def collect(self, algorithm, round_num, cwnd, ssthresh, state):
        self.records.append({
            "Algorithm": algorithm,
            "Round": round_num,
            "Cwnd": cwnd,
            "ssthresh": ssthresh,
            "State": state,
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    def to_dataframe(self):
        return pd.DataFrame(self.records)

    def save_to_csv(self, filepath=None):
        """수집된 Cwnd 데이터를 CSV 파일로 자동 저장"""
        if not self.records:
            return None
        if filepath is None:
            algo = self.records[0]["Algorithm"]
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"cwnd_data_{algo}_{ts}.csv"

        df = self.to_dataframe()
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return filepath

    def analyze(self):
        """수집된 데이터를 기반으로 기본 통계 분석 결과 반환"""
        df = self.to_dataframe()
        if df.empty:
            return {}

        # Cwnd가 감소한 라운드 횟수를 손실 이벤트 발생 횟수로 계산
        cwnd_diff = df["Cwnd"].diff()
        loss_events = int((cwnd_diff < 0).sum())

        return {
            "Algorithm": df["Algorithm"].iloc[0],
            "Total_Rounds": len(df),
            "Avg_Cwnd": round(float(df["Cwnd"].mean()), 2),
            "Max_Cwnd": round(float(df["Cwnd"].max()), 2),
            "Min_Cwnd": round(float(df["Cwnd"].min()), 2),
            "Loss_Event_Count": loss_events
        }


def run_socket_simulation(algorithm, loss_rate, rtt=100, total_rounds=20, save_files=True):
    """
    tcp_algorithm.py와 app.py 사이를 연결하는 통합 실행 함수
    """
    sim = TCPCongestionControlSimulator(
        algorithm=algorithm, initial_ssthresh=16, loss_rate=loss_rate
    )
    comm = PacketSocketCommunicator()
    collector = CwndDataCollectorAndAnalyzer()

    comm.start_receiver(rtt_ms=rtt)
    current_seq = 1

    try:
        for r in range(1, total_rounds + 1):
            #  팀원 A의 알고리즘으로 현재 라운드 상태 및 Cwnd 계산
            step_result = sim.step(r)
            cwnd_count = max(1, int(step_result["Cwnd"]))

            #  실제 소켓을 통해 Cwnd 크기만큼 패킷 전송 및 덤프 기록
            comm.send_packets(start_seq=current_seq, count=cwnd_count, rtt_ms=rtt)
            current_seq += cwnd_count

            #  Cwnd 변화 데이터 수집
            collector.collect(
                algorithm=algorithm,
                round_num=step_result["Round"],
                cwnd=step_result["Cwnd"],
                ssthresh=step_result["ssthresh"],
                state=step_result["State"]
            )
    finally:
        comm.stop_receiver()

    #  CSV 및 패킷 덤프 로그 파일 자동 저장
    csv_path = None
    log_path = None
    if save_files:
        csv_path = collector.save_to_csv()
        log_path = comm.save_dump_log(f"packet_dump_{algorithm}.log")

    analysis_summary = collector.analyze()

    return {
        "dataframe": collector.to_dataframe(),   # app.py 그래프 출력용 DataFrame
        "packet_dumps": comm.packet_dumps,       # 패킷 덤프 리스트
        "analysis": analysis_summary,            # 분석 결과 딕셔너리
        "csv_path": csv_path,                    # 저장된 CSV 파일 경로
        "log_path": log_path                     # 저장된 로그 파일 경로
    }
