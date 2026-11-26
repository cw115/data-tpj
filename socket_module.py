import json
import random
import socket
import threading
import time
from datetime import datetime
import pandas as pd
from tcp_algorithm import TCPCongestionControlSimulator


def default_network_impairment(loss_rate: float, rtt_ms: float, rng: random.Random = None) -> dict:
    """
    패킷 손실률(0~20%)과 RTT(0~500ms)를 기준으로 가상 네트워크 장애를 주입합니다.
    app.py의 inject_network_impairment와 동일한 반환 규격을 유지합니다.
    """
    rand_gen = rng if rng is not None else random
    clamped_loss = max(0.0, min(20.0, float(loss_rate)))
    clamped_rtt = max(0.0, min(500.0, float(rtt_ms)))

    is_dropped = rand_gen.uniform(0.0, 100.0) < clamped_loss
    delay_sec = clamped_rtt / 1000.0

    return {
        "is_dropped": is_dropped,
        "delay_sec": delay_sec,
        "applied_loss": clamped_loss,
        "applied_rtt_ms": clamped_rtt,
    }


class PacketSocketCommunicator:
    """UDP 소켓 송수신, 가상 네트워크 장애 주입(손실/지연), 패킷 덤프 기록 모듈"""

    def __init__(self, host="127.0.0.1", port=9999, seed=None):
        self.host = host
        self.port = port
        self.rng = random.Random(seed)
        self.packet_dumps = []
        self._stop_event = threading.Event()
        self._rx_thread = None
        self._lock = threading.Lock()

    def _record_dump(self, direction, pkt_type, seq, payload_info=""):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] {direction:<12} | {pkt_type:<8} | SEQ={seq:<4} | {payload_info}"
        with self._lock:
            self.packet_dumps.append(log_entry)

    def _apply_impairment(self, loss_rate, rtt_ms, impairment_fn=None):
        """가상 장애 주입 함수 호출 및 반환값 정규화"""
        if impairment_fn is not None:
            imp = impairment_fn(loss_rate=loss_rate, rtt_ms=rtt_ms)
        else:
            imp = default_network_impairment(loss_rate=loss_rate, rtt_ms=rtt_ms, rng=self.rng)

        is_dropped = bool(imp.get("is_dropped", False))
        delay_sec = max(0.0, float(imp.get("delay_sec", max(0.0, float(rtt_ms)) / 1000.0)))
        applied_loss = float(imp.get("applied_loss", loss_rate))
        applied_rtt_ms = float(imp.get("applied_rtt_ms", rtt_ms))

        return {
            "is_dropped": is_dropped,
            "delay_sec": delay_sec,
            "applied_loss": applied_loss,
            "applied_rtt_ms": applied_rtt_ms,
        }

    def _receiver_loop(self, rtt_ms, loss_rate=0.0, impairment_fn=None):
        """수신자(Receiver) UDP 소켓 스레드: DATA 패킷 수신, 지연 반영 및 ACK 회신"""
        rx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rx_sock.bind((self.host, self.port))
        rx_sock.settimeout(0.2)

        try:
            while not self._stop_event.is_set():
                try:
                    raw_data, sender_addr = rx_sock.recvfrom(1024)
                    packet = json.loads(raw_data.decode("utf-8"))
                    seq = packet.get("seq", 0)

                    self._record_dump(
                        "RECV (RX)", "DATA", seq, f"from {sender_addr[0]}:{sender_addr[1]}"
                    )

                    one_way_delay = max(0.0, float(rtt_ms) / 1000.0) / 2.0
                    if impairment_fn is not None:
                        imp = impairment_fn(loss_rate=0.0, rtt_ms=rtt_ms)
                        one_way_delay = max(0.0, float(imp.get("delay_sec", rtt_ms / 1000.0))) / 2.0

                    if one_way_delay > 0 and not self._stop_event.is_set():
                        time.sleep(one_way_delay)

                    ack_packet = json.dumps({"type": "ACK", "ack": seq + 1}).encode("utf-8")
                    rx_sock.sendto(ack_packet, sender_addr)
                    self._record_dump(
                        "SEND (RX)",
                        "ACK",
                        seq + 1,
                        f"ACK 회신 완료 (편도지연 {one_way_delay * 1000:.1f}ms)",
                    )

                except socket.timeout:
                    continue
                except Exception as exc:
                    if not self._stop_event.is_set():
                        self._record_dump("ERR (RX)", "SOCK", -1, f"수신 루프 예외: {exc}")
                    break
        finally:
            rx_sock.close()

    def start_receiver(self, rtt_ms=100, loss_rate=0.0, impairment_fn=None):
        """수신자 스레드 시작"""
        self.stop_receiver()
        self._stop_event.clear()
        self._rx_thread = threading.Thread(
            target=self._receiver_loop,
            args=(rtt_ms, loss_rate, impairment_fn),
            daemon=True,
        )
        self._rx_thread.start()
        time.sleep(0.05)

    def stop_receiver(self):
        """수신자 스레드 안전 종료"""
        self._stop_event.set()
        if self._rx_thread and self._rx_thread.is_alive():
            self._rx_thread.join(timeout=0.5)
        self._rx_thread = None

    def send_packets(self, start_seq, count, rtt_ms=100, loss_rate=0, impairment_fn=None):
        """
        송신자(Sender) UDP 소켓:
        현재 Cwnd 크기(count)만큼 패킷을 전송하면서 가상 장애 주입(손실/지연) 및 ACK 수신을 처리합니다.
        """
        imp_preview = self._apply_impairment(
            loss_rate=loss_rate, rtt_ms=rtt_ms, impairment_fn=impairment_fn
        )
        effective_delay_sec = imp_preview["delay_sec"]

        tx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx_sock.settimeout(max(0.5, effective_delay_sec * 2.5 + 0.2))

        pkt_stats = {
            "sent": 0,
            "dropped": 0,
            "ack_received": 0,
            "delayed_packets": 0,
            "total_delay_sec": 0.0,
        }

        try:
            for i in range(max(0, int(count))):
                seq = start_seq + i
                imp = self._apply_impairment(
                    loss_rate=loss_rate, rtt_ms=rtt_ms, impairment_fn=impairment_fn
                )

                if imp["is_dropped"]:
                    pkt_stats["dropped"] += 1
                    self._record_dump(
                        "DROP (CH)",
                        "LOSS",
                        seq,
                        f"가상 장애 패킷 드롭 (설정 손실률 {imp['applied_loss']:.1f}%)",
                    )
                    continue

                delay_sec = imp["delay_sec"]
                if delay_sec > 0:
                    send_delay = delay_sec / 2.0
                    time.sleep(send_delay)
                    pkt_stats["delayed_packets"] += 1
                    pkt_stats["total_delay_sec"] = round(
                        pkt_stats["total_delay_sec"] + send_delay, 4
                    )

                payload = json.dumps({"type": "DATA", "seq": seq}).encode("utf-8")
                tx_sock.sendto(payload, (self.host, self.port))
                pkt_stats["sent"] += 1
                self._record_dump(
                    "SEND (TX)",
                    "DATA",
                    seq,
                    f"to {self.host}:{self.port} (지연 {delay_sec * 1000:.1f}ms)",
                )

                try:
                    ack_raw, _ = tx_sock.recvfrom(1024)
                    ack_data = json.loads(ack_raw.decode("utf-8"))
                    pkt_stats["ack_received"] += 1
                    self._record_dump(
                        "RECV (TX)", "ACK", ack_data.get("ack"), "ACK 수신 확인"
                    )
                except socket.timeout:
                    pkt_stats["dropped"] += 1
                    self._record_dump(
                        "TIMEOUT (TX)", "ERR", seq, "ACK 응답 시간 초과"
                    )
        finally:
            tx_sock.close()

        return pkt_stats

    def save_dump_log(self, filepath="packet_dump.log"):
        """패킷 덤프 내역을 .log 파일로 누락 없이 저장"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(
                f"=== TCP Socket Packet Dump (Total Events: {len(self.packet_dumps)}) ===\n"
            )
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

    COLUMNS = [
        "Algorithm", "Round", "Cwnd", "ssthresh", "State",
        "DupAck", "Event", "Sent_Packets", "Ack_Received",
        "Dropped_Packets", "Delayed_Packets", "Total_Delay_Sec",
        "Loss_Rate(%)", "RTT(ms)", "Timestamp",
    ]

    def __init__(self):
        self.records = []

    def collect(self, algorithm, step_result, pkt_stats=None, loss_rate=0, rtt_ms=100):
        """
        tcp_algorithm.py의 step_result와 소켓 송수신/장애 주입 통계(pkt_stats)를 통합 수집
        """
        stats = pkt_stats or {
            "sent": 0,
            "dropped": 0,
            "ack_received": 0,
            "delayed_packets": 0,
            "total_delay_sec": 0.0,
        }

        self.records.append({
            "Algorithm": algorithm,
            "Round": int(step_result["Round"]),
            "Cwnd": float(step_result["Cwnd"]),
            "ssthresh": float(step_result["ssthresh"]),
            "State": str(step_result["State"]),
            "DupAck": int(step_result.get("DupAck", 0)),
            "Event": str(step_result.get("Event", "ACK")),
            "Sent_Packets": int(stats.get("sent", 0)),
            "Ack_Received": int(stats.get("ack_received", 0)),
            "Dropped_Packets": int(stats.get("dropped", 0)),
            "Delayed_Packets": int(stats.get("delayed_packets", 0)),
            "Total_Delay_Sec": float(stats.get("total_delay_sec", 0.0)),
            "Loss_Rate(%)": loss_rate,
            "RTT(ms)": rtt_ms,
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        })

    def to_dataframe(self):
        if not self.records:
            return pd.DataFrame(columns=self.COLUMNS)
        return pd.DataFrame(self.records)[self.COLUMNS]

    def save_to_csv(self, filepath=None, run_tag=None):
        """수집된 Cwnd 및 패킷 통계를 CSV 파일로 자동 저장"""
        df = self.to_dataframe()
        if df.empty:
            return None

        if filepath is None:
            algo = df["Algorithm"].iloc[0]
            tag = run_tag or datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"cwnd_data_{algo}_{tag}.csv"

        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        return filepath

    def analyze(self):
        """수집된 데이터를 기반으로 정량 통계 분석 결과 반환"""
        df = self.to_dataframe()
        if df.empty:
            return {}

        loss_events = int(df["Event"].isin(self.LOSS_EVENT_TYPES).sum())
        state_counts = df["State"].value_counts().to_dict()

        total_sent = int(df["Sent_Packets"].sum())
        total_dropped = int(df["Dropped_Packets"].sum())
        total_delayed = int(df["Delayed_Packets"].sum())
        total_delay_sec = round(float(df["Total_Delay_Sec"].sum()), 3)
        total_attempts = total_sent + total_dropped
        actual_loss_pct = (
            round((total_dropped / total_attempts * 100), 2) if total_attempts > 0 else 0.0
        )

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
            "Total_Delayed_Packets": total_delayed,
            "Total_Delay_Sec": total_delay_sec,
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
    host="127.0.0.1",
    port=9999,
):
    """
    tcp_algorithm.py, 장애 주입 함수(impairment_fn), 소켓 통신, 로그/CSV 수집,
    그리고 app.py 시각화를 한 흐름으로 연결하는 통합 실행 함수
    """
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    sim = TCPCongestionControlSimulator(
        algorithm=algorithm,
        initial_ssthresh=initial_ssthresh,
        loss_rate=loss_rate,
        seed=seed,
    )
    comm = PacketSocketCommunicator(host=host, port=port, seed=seed)
    collector = CwndDataCollectorAndAnalyzer()

    comm.start_receiver(rtt_ms=rtt, loss_rate=loss_rate, impairment_fn=impairment_fn)
    current_seq = 1

    try:
        for r in range(1, int(total_rounds) + 1):
            step_result = sim.step(r)
            cwnd_count = max(1, int(step_result["Cwnd"]))

            comm._record_dump(
                "ROUND (SYS)",
                "STEP",
                r,
                f"Algo={algorithm} | State={step_result['State']} | Cwnd={step_result['Cwnd']} | Event={step_result['Event']}",
            )

            pkt_stats = comm.send_packets(
                start_seq=current_seq,
                count=cwnd_count,
                rtt_ms=rtt,
                loss_rate=loss_rate,
                impairment_fn=impairment_fn,
            )
            current_seq += cwnd_count

            collector.collect(
                algorithm=algorithm,
                step_result=step_result,
                pkt_stats=pkt_stats,
                loss_rate=loss_rate,
                rtt_ms=rtt,
            )
    finally:
        comm.stop_receiver()

    csv_path = None
    log_path = None
    if save_files:
        csv_path = collector.save_to_csv(run_tag=run_tag)
        log_path = comm.save_dump_log(f"packet_dump_{algorithm}_{run_tag}.log")

    return {
        "dataframe": collector.to_dataframe(),
        "packet_dumps": comm.packet_dumps,
        "analysis": collector.analyze(),
        "csv_path": csv_path,
        "log_path": log_path,
    }
