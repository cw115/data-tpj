
# cd data-tpj
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


# 가상 장애 주입 함수 ----
def inject_network_impairment(loss_rate: float, rtt_ms: float) -> dict:
    clamped_loss = max(0.0, min(20.0, float(loss_rate)))
    clamped_rtt = max(0.0, min(500.0, float(rtt_ms)))

    return {
        "is_dropped": random.uniform(0.0, 100.0) < clamped_loss,
        "delay_sec": clamped_rtt / 1000.0,
        "applied_loss": clamped_loss,
        "applied_rtt_ms": clamped_rtt,
    }


# 백엔드 데이터 수신 인터페이스 ----
def stream_simulation_data(algorithm: str, loss_rate: int, rtt: int, result: dict):

    for _, packet in result["dataframe"].iterrows():
        yield {
            "Round": int(packet["Round"]),
            "Cwnd": float(packet["Cwnd"]),
            "Ssthresh": float(packet["ssthresh"]),
            "State": str(packet["State"]),
            "Event": str(packet["Event"]),
            "DupAck": int(packet["DupAck"]),
            "Sent_Packets": int(packet["Sent_Packets"]),
            "Ack_Received": int(packet["Ack_Received"]),
            "Dropped_Packets": int(packet["Dropped_Packets"]),
            "Delayed_Packets": int(packet["Delayed_Packets"]),
            "Total_Delay_Sec": float(packet["Total_Delay_Sec"]),
            "DelaySec": rtt / 1000.0,
            "Algorithm": algorithm,
            "LossRate": loss_rate,
            "RTT": rtt,
        }


# 실행 결과 및 오류 상태 초기화 ----
if "simulation_result" not in st.session_state:
    st.session_state["simulation_result"] = None

if "simulation_error" not in st.session_state:
    st.session_state["simulation_error"] = None


# 시뮬레이션 설정 UI ----
st.subheader("시뮬레이션 설정")

algorithm = st.selectbox(
    "TCP 알고리즘 선택",
    ["Tahoe", "Reno"]
)

loss_rate = st.slider(
    "패킷 손실률 (%)",
    0, 20, 5
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

settings = {
    "algorithm": algorithm,
    "loss_rate": int(loss_rate),
    "rtt": int(rtt),
    "total_rounds": int(total_rounds),
}

run_clicked = st.button("시뮬레이션 실행")


# 실행 및 재실행 상태 관리 ----
if run_clicked:

    # 이전 결과와 오류 초기화
    st.session_state["simulation_result"] = None
    st.session_state["simulation_error"] = None

    try:
        with st.spinner("시뮬레이션 실행 중입니다..."):

            # 가상 장애 주입 함수 연결
            result = run_socket_simulation(
                **settings,
                save_files=True,
                impairment_fn=inject_network_impairment
            )

            records = list(stream_simulation_data(
                algorithm=algorithm,
                loss_rate=int(loss_rate),
                rtt=int(rtt),
                result=result,
            ))

            if not records:
                raise ValueError("시뮬레이션 결과 데이터가 없습니다.")

            # 실행 조건과 결과를 함께 저장
            st.session_state["simulation_result"] = {
                "settings": settings.copy(),
                "result": result,
                "records": records,
            }

    except Exception as exc:
        st.session_state["simulation_error"] = str(exc)


saved = st.session_state["simulation_result"]
error = st.session_state["simulation_error"]


# 오류 및 초기 화면 안내 ----
if error is not None:
    st.error(f"시뮬레이션 실행 실패: {error}")

if saved is None and error is None:
    st.info("조건을 설정한 후 시뮬레이션 실행 버튼을 눌러주세요.")


# 저장된 실행 결과 표시 ----
if saved is not None:

    used = saved["settings"]
    result = saved["result"]
    records = saved["records"]

    # 설정 변경 시 이전 실행 결과임을 안내
    if settings != used:
        st.warning(
            "설정이 변경되었습니다. 아래는 이전 실행 결과입니다. "
            "다시 실행하면 새 결과가 표시됩니다."
        )

    st.write(
        f"실행 조건: {used['algorithm']} | "
        f"패킷 손실률: {used['loss_rate']}% | "
        f"RTT: {used['rtt']} ms | "
        f"라운드: {used['total_rounds']}"
    )

    current_df = pd.DataFrame(records).set_index("Round")

    graph_df = current_df[["Cwnd", "Ssthresh"]].rename(
        columns={"Ssthresh": "ssthresh"}
    )

    status_box = st.empty()

    st.subheader("Cwnd / ssthresh 변화 그래프")
    chart = st.empty()

    # 새 실행에서만 그래프를 라운드별로 재생
    if run_clicked:

        for i, packet_info in enumerate(records):

            status_box.info(
                f"결과 표시 중 | "
                f"Round {packet_info['Round']}/{used['total_rounds']} | "
                f"Cwnd: {packet_info['Cwnd']} MSS | "
                f"ssthresh: {packet_info['Ssthresh']} MSS | "
                f"상태: {packet_info['State']} | "
                f"이벤트: {packet_info['Event']} | "
                f"중복 ACK: {packet_info['DupAck']}"
            )

            chart.line_chart(
                graph_df.iloc[:i + 1],
                x_label="Round",
                y_label="Window Size (MSS)"
            )

            time.sleep(
                max(0.05, min(0.8, packet_info["DelaySec"]))
            )

    else:
        # 설정 변경 등으로 화면이 다시 실행되어도
        # 저장된 결과를 유지하고 소켓은 재호출하지 않음
        chart.line_chart(
            graph_df,
            x_label="Round",
            y_label="Window Size (MSS)"
        )

    last = records[-1]

    status_box.success(
        f"시뮬레이션 완료! | "
        f"최종 상태: {last['State']} | "
        f"최종 이벤트: {last['Event']} | "
        f"중복 ACK: {last['DupAck']}"
    )


    # 라운드별 패킷 정보 ----
    st.subheader("라운드별 패킷 손실 및 지연 정보")

    st.dataframe(
        current_df[[
            "State",
            "Event",
            "DupAck",
            "Sent_Packets",
            "Ack_Received",
            "Dropped_Packets",
            "Delayed_Packets",
            "Total_Delay_Sec"
        ]]
    )


    # 통계 분석 요약 ----
    st.subheader("통계 분석 요약")

    analysis = result["analysis"]

    col1, col2, col3 = st.columns(3)

    col1.metric("평균 Cwnd", analysis["Avg_Cwnd"])
    col2.metric("최대 Cwnd", analysis["Max_Cwnd"])
    col3.metric("최종 Cwnd", analysis["Final_Cwnd"])

    col4, col5, col6 = st.columns(3)

    col4.metric("총 송신 패킷", analysis["Total_Sent_Packets"])
    col5.metric("총 손실 패킷", analysis["Total_Dropped_Packets"])
    col6.metric(
        "집계 손실률",
        f"{analysis['Actual_Channel_Loss(%)']}%"
    )

    st.write(
        "혼잡 제어 손실 이벤트 수:",
        analysis["Loss_Event_Count"]
    )

    st.write(
        "지연 패킷 수:",
        analysis["Total_Delayed_Packets"]
    )

    st.write(
        "누적 송신 측 지연 시간:",
        analysis["Total_Delay_Sec"],
        "초"
    )

    st.caption(
        "집계 손실률은 백엔드 계산 기준이며, "
        "누적 지연 시간은 실제 측정 RTT와 다릅니다."
    )


    # 패킷 덤프 표시 ----
    st.subheader("패킷 덤프")

    packet_dumps = result["packet_dumps"]

    st.write("총 패킷 기록 수:", len(packet_dumps))

    with st.expander("패킷 송수신 로그 보기"):
        st.code("\n".join(packet_dumps), language="text")
