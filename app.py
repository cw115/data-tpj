# python -m streamlit run app.py

import streamlit as st
import pandas as pd
import time
from socket_module import run_socket_simulation

# 기본 화면 ----
st.set_page_config(
    page_title="TCP 혼잡 제어 시뮬레이터",
    layout="wide"
)

st.title("TCP 혼잡 제어 시뮬레이터")
st.write("TCP Tahoe / Reno 혼잡 제어 동작 시각화")


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
    min_value=1,
    value=100
)


# 시뮬레이션 실행 및 결과 표시 ----
if st.button("시뮬레이션 실행"):
    st.success("시뮬레이션 설정 완료!")
    st.write("알고리즘:", algorithm)
    st.write("패킷 손실률:", loss_rate, "%")
    st.write("RTT:", rtt, "ms")
    
    # 소켓 통신 및 TCP 알고리즘 시뮬레이션 실행
    with st.spinner("소켓 패킷 송수신 및 시뮬레이션 진행 중..."):
        result = run_socket_simulation(
            algorithm=algorithm, 
            loss_rate=loss_rate, 
            rtt=rtt,
            total_rounds=20,
            save_files=True
        )
    
    data = result["dataframe"]
    packet_dumps = result["packet_dumps"]
    analysis = result["analysis"]

    # Cwnd 실시간 그래프
    st.subheader("Cwnd 변화 그래프")
    chart = st.empty()

    for i in range(len(data)):
        current_data = data.iloc[:i+1]

        chart.line_chart(
            current_data.set_index("Round")[["Cwnd"]],
            x_label="Round",
            y_label="Cwnd (MSS)"
        )

        # 설정한 RTT에 비례하여 그래프 갱신 속도 조절
        time.sleep(max(0.05, rtt / 1000.0))

    # 소켓 통신 결과 (분석 요약, 패킷 덤프, CSV 다운로드) 연동
    st.divider()
    st.subheader("시뮬레이션 결과 분석 및 로그")

    # 1. 데이터 분석 요약 지표 출력
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("평균 Cwnd", f"{analysis.get('Avg_Cwnd', 0)} MSS")
    col2.metric("최대 Cwnd", f"{analysis.get('Max_Cwnd', 0)} MSS")
    col3.metric("최소 Cwnd", f"{analysis.get('Min_Cwnd', 0)} MSS")
    col4.metric("손실 발생 횟수", f"{analysis.get('Loss_Event_Count', 0)} 회")

    # 2. CSV 다운로드 버튼
    csv_bytes = data.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label="Cwnd 데이터 CSV 다운로드",
        data=csv_bytes,
        file_name=f"cwnd_result_{algorithm}.csv",
        mime="text/csv"
    )

    # 3. 소켓 패킷 덤프 및 상세 데이터 탭
    tab1, tab2 = st.tabs(["소켓 패킷 덤프 로그", "라운드별 상세 데이터"])
    with tab1:
        st.code("\n".join(packet_dumps), language="text")
    with tab2:
        st.dataframe(data, use_container_width=True)
