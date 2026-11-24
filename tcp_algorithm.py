import random
import pandas as pd


class TCPCongestionControlSimulator:
    def __init__(self, algorithm="Tahoe", initial_ssthresh=16, loss_rate=5, seed=None):
        self.algorithm = algorithm
        self.ssthresh = float(initial_ssthresh)
        self.cwnd = 1.0
        self.loss_rate = loss_rate  # 패킷 손실률 (%)
        self.rng = random.Random(seed)

        # 상태: 'SLOW_START', 'CONGESTION_AVOIDANCE', 'FAST_RECOVERY'
        self.state = "SLOW_START"
        self.dup_ack_count = 0  # 중복 ACK 카운터 (Reno에서 사용)

    def _apply_timeout_reset(self):
        """타임아웃(또는 Tahoe 손실) 시 ssthresh 갱신 및 cwnd=1 초기화"""
        self.ssthresh = max(self.cwnd / 2.0, 2.0)
        self.cwnd = 1.0
        self.state = "SLOW_START"
        self.dup_ack_count = 0

    def step(self, round_num):
        """
        1개의 RTT(라운드) 동안 발생하는 TCP 혼잡 제어 상태 전이 및 cwnd 계산 로직
        """
        # 1. 패킷 손실 시뮬레이션 (설정된 패킷 손실률에 따라 확률적으로 손실 발생)
        is_loss = self.rng.randint(1, 100) <= self.loss_rate
        event = "ACK"

        if is_loss:
            if self.algorithm == "Tahoe":
                # Tahoe: 손실 발생 시 ssthresh 갱신 후 cwnd를 1로 낮추고 SLOW_START로 복귀
                self._apply_timeout_reset()
                event = "LOSS_TAHOE_RESET"

            elif self.algorithm == "Reno":
                # Reno: 이미 FAST_RECOVERY 중 추가 손실이 나면 타임아웃으로 간주해 초기화
                if self.state == "FAST_RECOVERY":
                    self._apply_timeout_reset()
                    event = "TIMEOUT_IN_RECOVERY"
                else:
                    # 3중 중복 ACK(Triple Duplicate ACK) 도달 시 Fast Retransmit & Fast Recovery 진입
                    self.dup_ack_count = 3
                    self.ssthresh = max(self.cwnd / 2.0, 2.0)
                    self.cwnd = self.ssthresh + self.dup_ack_count
                    self.state = "FAST_RECOVERY"
                    event = "TRIPLE_DUP_ACK_FAST_RECOVERY"
            else:
                raise ValueError(f"지원하지 않는 알고리즘입니다: {self.algorithm}")
        else:
            # 정상 ACK 수신 시 상태별 cwnd 및 dup_ack_count 갱신
            if self.state == "FAST_RECOVERY":
                # Fast Recovery 상태에서 새 ACK 수신 -> ssthresh로 deflate 후 CONGESTION_AVOIDANCE 진입
                self.cwnd = self.ssthresh
                self.state = "CONGESTION_AVOIDANCE"
                self.dup_ack_count = 0
                event = "EXIT_FAST_RECOVERY"

            elif self.state == "SLOW_START":
                # 느린 시작: RTT마다 cwnd가 2배씩 증가
                self.cwnd *= 2.0
                self.dup_ack_count = 0
                if self.cwnd >= self.ssthresh:
                    self.state = "CONGESTION_AVOIDANCE"
                    event = "ENTER_CONGESTION_AVOIDANCE"

            elif self.state == "CONGESTION_AVOIDANCE":
                # 혼잡 회피: RTT마다 cwnd가 1씩 증가(AIMD의 Additive Increase)
                self.cwnd += 1.0
                self.dup_ack_count = 0

        return {
            "Round": round_num,
            "Cwnd": round(self.cwnd, 2),
            "ssthresh": round(self.ssthresh, 2),
            "State": self.state,
            "DupAck": self.dup_ack_count,
            "Event": event,
        }


# 결과값을 리스트업해서 UI에 사용할 데이터프레임으로 변환
def generate_simulation_data(algorithm, loss_rate, total_rounds=20, initial_ssthresh=16, seed=None):
    sim = TCPCongestionControlSimulator(
        algorithm=algorithm,
        initial_ssthresh=initial_ssthresh,
        loss_rate=loss_rate,
        seed=seed,
    )
    history = []

    for r in range(1, total_rounds + 1):
        result = sim.step(r)
        history.append(result)

    return pd.DataFrame(history)
