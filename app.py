# python -m streamlit run app.py

import random
import time
import pandas as pd
import streamlit as st
from socket_module import run_socket_simulation

# 기본 화면 ----
st.set_page_config(
    page_title="TCP 혼잡 제어 시뮬레이터",
    layout="wide"
)

st.title("TCP 혼잡 제어 시뮬레이터")
st.write("TCP Tahoe / Reno 혼잡 제어 동작 시각화")


# [1순위] 가상 장애 주입 함수 설계 ----
def inject_network_impairment(loss_rate: float, rtt_ms: float) -> dict:
    """
    패킷 손실률(0~20%)과 RTT(0~500ms)를 기준으로 가상 네트워크 장애를 주입합니다.

    반환값:
        - is_dropped (bool): 패킷 손실 발생 여부
        - delay_sec (float): 적용할 지연 시간(초)
    """
    clamped_loss = max(0.0, min(20.0, float(loss_rate)))
    clamped_rtt = max(0.0, min(500.0, float(rtt_ms)))

    # 패킷 손실 판정 (0~100 난수 기반)
    is_dropped = random.uniform(0.0, 100.0) < clamped_loss

    # RTT 기반 지연 시간 계산 (밀리초 -> 초 변환)
    delay_sec = clamped_rtt / 1000.0

    return {
        "is_dropped": is_dropped,
        "delay_sec": delay_sec,
        "applied_loss": clamped_loss,
        "applied_rtt_ms": clamped_rtt,
    }


# 백엔드(소켓/알고리즘 엔진) 연동용 데이터 수신 인터페이스 ----

# 실제 소켓 통신 데이터 수신 인터페이스
def stream_simulation_data(algorithm: str, loss_rate: int, rtt: int, rounds: int = 10):
    """
    팀원들이 구현한 소켓 통신과 TCP 혼잡 제어 결과를 받아
    Streamlit UI에서 사용할 수 있는 형태로 변환합니다.
    """

    result = run_socket_simulation(
        algorithm=algorithm,
        loss_rate=loss_rate,
        rtt=rtt,
        total_rounds=rounds,
        save_files=True
    )

    data = result["dataframe"]

    for _, packet in data.iterrows():
        yield {
            "Round": int(packet["Round"]),
            "Cwnd": float(packet["Cwnd"]),
            "Ssthresh": float(packet["ssthresh"]),
            "Event": str(packet["State"]),
            "DelaySec": rtt / 1000.0,
            "Algorithm": algorithm,
            "LossRate": loss_rate,
            "RTT": rtt,
        }


# 시뮬레이션 설정 UI ----
st.subheader("시뮬레이션 설정")

algorithm = st.selectbox(
    "TCP 알고리즘 선택",
    ["Tahoe", "Reno"]
)

loss_rate = st.slider(
    "패킷 손실률 (%)",
    min_value=0,
    max_value=20,
    value=5
)

rtt = st.number_input(
    "RTT (ms)",
    min_value=0,
    max_value=500,
    value=100
)

total_rounds = st.number_input(
    "시뮬레이션 라운드 수",
    min_value=1,
    max_value=100,
    value=10
)


# 시뮬레이션 실행 및 결과 표시 ----
if st.button("시뮬레이션 실행"):
    st.success("시뮬레이션 설정 완료!")
    st.write("알고리즘:", algorithm)
    st.write("패킷 손실률:", loss_rate, "%")
    st.write("RTT:", rtt, "ms")

    status_box = st.empty()
    st.subheader("Cwnd 변화 그래프")
    chart = st.empty()

    records = []

    for packet_info in stream_simulation_data(
        algorithm=algorithm,
        loss_rate=loss_rate,
        rtt=int(rtt),
        rounds=int(total_rounds),
    ):
        records.append({
            "Round": packet_info["Round"],
            "Cwnd": packet_info["Cwnd"],
        })
        current_df = pd.DataFrame(records).set_index("Round")

        status_box.info(
            f"Round {packet_info['Round']}/{int(total_rounds)} | "
            f"Cwnd: {packet_info['Cwnd']} MSS | "
            f"이벤트: {packet_info['Event']}"
        )
        chart.line_chart(
            current_df,
            x_label="Round",
            y_label="Cwnd (MSS)"
        )

        # 화면이 너무 오래 멈추지 않도록 시각적 대기 시간 상한 설정
        time.sleep(max(0.05, min(0.8, packet_info["DelaySec"])))

    status_box.success("시뮬레이션 완료!")
