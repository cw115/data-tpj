import pandas as pd
import random

class TCPCongestionControlSimulator:
    def __init__(self, algorithm="Tahoe", initial_ssthresh=16, loss_rate=5):
        self.algorithm = algorithm
        self.ssthresh = float(initial_ssthresh)
        self.cwnd = 1.0
        self.loss_rate = loss_rate # 패킷 손실률 (%)
        
        # 상태: 'SLOW_START', 'CONGESTION_AVOIDANCE', 'FAST_RECOVERY'
        self.state = "SLOW_START"
        self.dup_ack_count = 0  # 중복 ACK 카운터 (Reno에서 사용)

    def step(self, round_num):
        """
        1개의 RTT(라운드) 동안 발생하는 TCP 혼잡 제어 상태 전이 및 cwnd 계산 로직
        """
        # 1. 패킷 손실 시뮬레이션 (설정된 패킷 손실률에 따라 확률적으로 손실 발생)
        is_loss = random.randint(1, 100) <= self.loss_rate

        if is_loss:
            # 손실 발생 시 공통: ssthresh는 현재 cwnd의 절반으로 감
            self.ssthresh = max(self.cwnd / 2.0, 2.0)
            
            if self.algorithm == "Tahoe":
                # Tahoe: 손실 발생 시 무조건 cwnd를 1로 낮추고 Slow Start로 복귀
                self.cwnd = 1.0
                self.state = "SLOW_START"
                self.dup_ack_count = 0
                
            elif self.algorithm == "Reno":
                # Reno: 3중 중복 ACK 상황 가정
                # cwnd를 ssthresh + 3으로 설정하고 빠른회피 진입 
                self.cwnd = self.ssthresh + 3.0
                self.state = "FAST_RECOVERY"
        else:
            # 정상적인 ACK 수신 시 상태별 cwnd 계산
            if self.state == "SLOW_START":
                # 느린 시작: RTT마다 cwnd가 2배씩 증가
                self.cwnd *= 2.0
                # ssthresh에 도달하거나 넘으면 혼잡 회피 단계로 전환
                if self.cwnd >= self.ssthresh:
                    self.state = "CONGESTION_AVOIDANCE"
                    
            elif self.state == "CONGESTION_AVOIDANCE":
                # 혼잡 회피: RTT마다 cwnd가 1씩 증가
                self.cwnd += 1.0
                
            elif self.state == "FAST_RECOVERY":
                # 빠른 회복 단계 탈출 후 혼잡 회피로 복귀
                self.cwnd = self.ssthresh
                self.state = "CONGESTION_AVOIDANCE"

        return {
            "Round": round_num,
            "Cwnd": round(self.cwnd, 2),
            "ssthresh": round(self.ssthresh, 2),
            "State": self.state
        }


# 결과값을 리스트업해서 UI에 사용할 데이터프레임으로 변환 
def generate_simulation_data(algorithm, loss_rate, total_rounds=20):

    sim = TCPCongestionControlSimulator(algorithm=algorithm, initial_ssthresh=16, loss_rate=loss_rate)
    history = []

    for r in range(1, total_rounds + 1):
        result = sim.step(r)
        history.append(result)

    return pd.DataFrame(history)
