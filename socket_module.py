import socket
import threading
import time
import json
import random
from datetime import datetime
import pandas as pd
from tcp_algorithm import TCPCongestionControlSimulator


class PacketSocketCommunicator:
    """Python socket 기반 송수신자 간 기본 패킷 전송 및 덤프 모듈"""

    def __init__(self, host="127.0.0.1", port=9999):
        self.host = host
        self.port = port
        self.packet_dumps = []  # 패킷 덤프 기록 리스트
        self._stop_event = threading.Event()
        self._rx_thread = None

    def _record_dump(self, direction, pkt_type, seq, payload_info=""):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {direction:<12} | {pkt_type:<8} | SEQ={seq:<4} | {payload_info}"
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

    def send_packets(self, start_seq, count, rtt_ms=100, loss_rate=0, impairment_fn=None):
        """
        송신자(Sender) 소켓: 현재 Cwnd 개수만큼 패킷을 전송하고 장애 주입(손실/지연) 및 ACK 수신 처리
        - impairment_fn: app.py의 inject_network_impairment(loss_rate, rtt_ms) 규격 함수
        """
        tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx_sock.settimeout(max(0.5, (rtt_ms / 1000.0) * 2))

        pkt_stats = {"sent": 0, "dropped": 0, "ack_received": 0}

        try:
            for i in range(count):
                seq = start_seq + i

                # 가상 장애 주입 판정 (app.py의 inject_network_impairment 규격 연동)
                if impairment_fn is not None:
                    imp = impairment_fn(loss_rate=loss_rate, rtt_ms=rtt_ms)
                    is_dropped = bool(imp.get("is_dropped", False))
                    delay_sec = float(imp.get("delay_sec", 0.0))
                else:
                    is_dropped = random.uniform(0.0, 100.0) < float(loss_rate)
                    delay_sec = (rtt_ms / 1000.0) / 2.0

                if is_dropped:
                    pkt_stats["dropped"] += 1
                    self._record_dump("DROP (CH)", "LOSS", seq, f"가상 채널 패킷 손실 (손실률 {loss_rate}%)")
                    continue

                if delay_sec > 0:
                    time.sleep(delay_sec / 2.0)

                payload = json.dumps({"type": "DATA", "seq": seq}).encode("utf-8")
                tx_sock.sendto(payload, (self.host, self.port))
                pkt_stats["sent"] += 1
                self._record_dump("SEND (TX)", "DATA", seq, f"to {self.host}:{self.port}")

                try:
                    ack_raw, _ = tx_sock.recvfrom(1024)
                    ack_data = json.loads(ack_raw.decode("utf-8"))
                    pkt_stats["ack_received"] += 1
                    self._record_dump("RECV (TX)", "ACK", ack_data.get("ack"), "ACK 수신 확인")
                except socket.timeout:
                    pkt_stats["dropped"] += 1
                    self._record_dump("TIMEOUT (TX)", "ERR", seq, "ACK 응답 시간 초과")
        finally:
            tx_sock.close()

        return pkt_stats

    def save_dump_log(self, filepath="packet_dump.log"):
        """패킷 덤프 내역을 .log 파일로 누락 없이 저장"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"=== TCP Socket Packet Dump (Total Events: {len(self.packet_dumps)}) ===\n")
            for line in self.packet_dumps:
                f.write(line + "\n")
        return filepath


class CwndDataCollectorAndAnalyzer:
    """알고리즘별 Cwnd 변화 데이터(CSV/로그) 자동 수집 및 통계 분석 모듈"""

    LOSS_EVENT_TYPES = {
        "LOSS_TAHOE_RESET",
        "TIMEOUT_IN_RECOVERY",
        "TRIPLE_DUP_ACK_FAST_RECOVERY",
    }

    def __init__(self):
        self.records = []

    def collect(self, algorithm, step_result, pkt_stats=None, loss_rate=0, rtt_ms=100):
        """
        tcp_algorithm.py의 step_result(Round, Cwnd, ssthresh, State, DupAck, Event)와
        소켓 송수신 통계(pkt_stats)를 누락 없이 통합 수집
        """
        pkt_stats = pkt_stats or {"sent": 0, "dropped": 0, "ack_received": 0}

        self.records.append({
            "Algorithm": algorithm,
            "Round": int(step_result["Round"]),
            "Cwnd": float(step_result["Cwnd"]),
            "ssthresh": float(step_result["ssthresh"]),
            "State": str(step_result["State"]),
            "DupAck": int(step_result.get("DupAck", 0)),
            "Event": str(step_result.get("Event", "ACK")),
            "Sent_Packets": int(pkt_stats.get("sent", 0)),
            "Ack_Received": int(pkt_stats.get("ack_received", 0)),
            "Dropped_Packets": int(pkt_stats.get("dropped", 0)),
            "Loss_Rate(%)": loss_rate,
            "RTT(ms)": rtt_ms,
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        })

    def to_dataframe(self):
        if not self.records:
            return pd.DataFrame(columns=[
                "Algorithm", "Round", "Cwnd", "ssthresh", "State",
                "DupAck", "Event", "Sent_Packets", "Ack_Received",
                "Dropped_Packets", "Loss_Rate(%)", "RTT(ms)", "Timestamp"
            ])
        return pd.DataFrame(self.records)

    def save_to_csv(self, filepath=None):
        """수집된 Cwnd 및 패킷 통계를 CSV 파일로 자동 저장"""
        df = self.to_dataframe()
        if df.empty:
            return None

        if filepath is None:
            algo = df["Algorithm"].iloc[0]
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"cwnd_data_{algo}_{ts}.csv"

        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return filepath

    def analyze(self):
        """수집된 데이터를 기반으로 정량 통계 분석 결과 반환 (benchmark.py 지표와 통일)"""
        df = self.to_dataframe()
        if df.empty:
            return {}

        loss_events = int(df["Event"].isin(self.LOSS_EVENT_TYPES).sum())
        state_counts = df["State"].value_counts().to_dict()

        total_sent = int(df["Sent_Packets"].sum())
        total_dropped = int(df["Dropped_Packets"].sum())
        total_attempts = total_sent + total_dropped
        actual_loss_pct = round((total_dropped / total_attempts * 100), 2) if total_attempts > 0 else 0.0

        return {
            "Algorithm": df["Algorithm"].iloc[0],
            "Total_Rounds": int(len(df)),
            "Avg_Cwnd": round(float(df["Cwnd"].mean()), 2),
            "Total_Cwnd_Sum": round(float(df["Cwnd"].sum()), 2),
            "Max_Cwnd": round(float(df["Cwnd"].max()), 2),
            "Min_Cwnd": round(float(df["Cwnd"].min()), 2),
            "Final_Cwnd": round(float(df["Cwnd"].iloc[-1]), 2),
            "Loss_Event_Count": loss_events,
            "SlowStart_Rounds": int(state_counts.get("SLOW_START", 0)),
            "CongAvoid_Rounds": int(state_counts.get("CONGESTION_AVOIDANCE", 0)),
            "FastRecovery_Rounds": int(state_counts.get("FAST_RECOVERY", 0)),
            "Total_Sent_Packets": total_sent,
            "Total_Dropped_Packets": total_dropped,
            "Actual_Channel_Loss(%)": actual_loss_pct,
        }


def run_socket_simulation(
    algorithm,
    loss_rate,
    rtt=100,
    total_rounds=20,
    save_files=True,
    initial_ssthresh=16,
    seed=None,
    impairment_fn=None,
):
    """
    tcp_algorithm.py, 장애 주입 함수(impairment_fn), app.py 사이를 연결하는 통합 실행 함수
    """
    sim = TCPCongestionControlSimulator(
        algorithm=algorithm,
        initial_ssthresh=initial_ssthresh,
        loss_rate=loss_rate,
        seed=seed,
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

         #   실제 소켓 전송 + 장애 주입(손실/지연) + 패킷 덤프 기록
            pkt_stats = comm.send_packets(
                start_seq=current_seq,
                count=cwnd_count,
                rtt_ms=rtt,
                loss_rate=loss_rate,
                impairment_fn=impairment_fn,
            )
            current_seq += cwnd_count

          #  Cwnd 변화 데이터 + 이벤트 + 패킷 통계 통합 수집
            collector.collect(
                algorithm=algorithm,
                step_result=step_result,
                pkt_stats=pkt_stats,
                loss_rate=loss_rate,
                rtt_ms=rtt,
            )
    finally:
        comm.stop_receiver()

    # CSV 및 패킷 덤프 로그 파일 자동 저장
    csv_path = None
    log_path = None
    if save_files:
        csv_path = collector.save_to_csv()
        log_path = comm.save_dump_log(f"packet_dump_{algorithm}.log")

    return {
        "dataframe": collector.to_dataframe(),   # app.py 그래프/스트림 출력용 DataFrame
        "packet_dumps": comm.packet_dumps,       # 패킷 덤프 리스트
        "analysis": collector.analyze(),         # 정량 통계 분석 결과 딕셔너리
        "csv_path": csv_path,                    # 자동 저장된 CSV 파일 경로
        "log_path": log_path,                    # 자동 저장된 로그 파일 경로
    }
