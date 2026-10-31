# python -m streamlit run app.py

import streamlit as st
import pandas as pd
import time

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


# Cwnd 그래프 테스트용 임시 데이터 (삭제 예정) ----
data = pd.DataFrame({
    "Round": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "Cwnd": [1, 2, 4, 8, 16, 8, 9, 10, 11, 12]
})


# 시뮬레이션 실행 및 결과 표시 ----
if st.button("시뮬레이션 실행"):
    st.success("시뮬레이션 설정 완료!")
    st.write("알고리즘:", algorithm)
    st.write("패킷 손실률:", loss_rate, "%")
    st.write("RTT:", rtt, "ms")

    # Cwnd 실시간 그래프
    st.subheader("Cwnd 변화 그래프")
    chart = st.empty()

    for i in range(len(data)):
        current_data = data.iloc[:i+1]

        chart.line_chart(
            current_data.set_index("Round"),
            x_label="Round",
            y_label="Cwnd (MSS)"
        )

        time.sleep(0.5)
