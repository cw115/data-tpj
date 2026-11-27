import pandas as pd
from tcp_algorithm import generate_simulation_data


def evaluate_single_run(df: pd.DataFrame) -> dict:
    """단일 시뮬레이션 결과 DataFrame에서 정량 지표 추출"""
    loss_events = int(df["Event"].isin(["LOSS_TAHOE_RESET", "TIMEOUT_IN_RECOVERY", "TRIPLE_DUP_ACK_FAST_RECOVERY"]).sum())
    state_counts = df["State"].value_counts().to_dict()

    return {
        "Avg_Cwnd": round(float(df["Cwnd"].mean()), 2),
        "Total_Cwnd_Sum": round(float(df["Cwnd"].sum()), 2),
        "Max_Cwnd": round(float(df["Cwnd"].max()), 2),
        "Min_Cwnd": round(float(df["Cwnd"].min()), 2),
        "Final_Cwnd": round(float(df["Cwnd"].iloc[-1]), 2),
        "Loss_Events": loss_events,
        "SlowStart_Rounds": int(state_counts.get("SLOW_START", 0)),
        "CongAvoid_Rounds": int(state_counts.get("CONGESTION_AVOIDANCE", 0)),
        "FastRecovery_Rounds": int(state_counts.get("FAST_RECOVERY", 0)),
    }


def run_quantitative_benchmark(
    loss_rates=(0, 5, 8, 15),
    initial_ssthresh_list=(16,),
    total_rounds=20,
    num_trials=30,
    base_seed=42,
):
    raw_rows = []

    for ssthresh in initial_ssthresh_list:
        for loss_rate in loss_rates:
            for trial in range(num_trials):
                seed = base_seed + trial

                for algo in ("Tahoe", "Reno"):
                    df = generate_simulation_data(
                        algorithm=algo,
                        loss_rate=loss_rate,
                        total_rounds=total_rounds,
                        initial_ssthresh=ssthresh,
                        seed=seed,
                    )
                    metrics = evaluate_single_run(df)
                    raw_rows.append({
                        "Trial": trial + 1,
                        "Seed": seed,
                        "Initial_ssthresh": ssthresh,
                        "Loss_Rate": loss_rate,
                        "Algorithm": algo,
                        **metrics,
                    })

    raw_df = pd.DataFrame(raw_rows)

    # 조건별(Initial_ssthresh, Loss_Rate, Algorithm) 평균 집계
    summary_df = (
        raw_df.groupby(["Initial_ssthresh", "Loss_Rate", "Algorithm"], as_index=False)[
            [
                "Avg_Cwnd",
                "Total_Cwnd_Sum",
                "Max_Cwnd",
                "Min_Cwnd",
                "Final_Cwnd",
                "Loss_Events",
                "SlowStart_Rounds",
                "CongAvoid_Rounds",
                "FastRecovery_Rounds",
            ]
        ]
        .mean()
        .round(2)
    )

    # 동일 조건에서 Reno vs Tahoe 평균 Cwnd 차이 및 개선율(%) 계산
    tahoe_df = summary_df[summary_df["Algorithm"] == "Tahoe"].set_index(["Initial_ssthresh", "Loss_Rate"])
    reno_df = summary_df[summary_df["Algorithm"] == "Reno"].set_index(["Initial_ssthresh", "Loss_Rate"])

    comparison_df = pd.DataFrame({
        "Tahoe_Avg_Cwnd": tahoe_df["Avg_Cwnd"],
        "Reno_Avg_Cwnd": reno_df["Avg_Cwnd"],
        "Avg_Cwnd_Diff": (reno_df["Avg_Cwnd"] - tahoe_df["Avg_Cwnd"]).round(2),
        "Reno_Improvement_%": (
            ((reno_df["Avg_Cwnd"] - tahoe_df["Avg_Cwnd"]) / tahoe_df["Avg_Cwnd"].replace(0, pd.NA)) * 100
        ).astype(float).round(2),
        "Tahoe_Total_Sum": tahoe_df["Total_Cwnd_Sum"],
        "Reno_Total_Sum": reno_df["Total_Cwnd_Sum"],
        "Tahoe_Loss_Events": tahoe_df["Loss_Events"],
        "Reno_Loss_Events": reno_df["Loss_Events"],
    }).reset_index()

    raw_df.to_csv("benchmark_raw_trials.csv", index=False, encoding="utf-8-sig")
    summary_df.to_csv("benchmark_summary.csv", index=False, encoding="utf-8-sig")
    comparison_df.to_csv("benchmark_tahoe_vs_reno.csv", index=False, encoding="utf-8-sig")

    return raw_df, summary_df, comparison_df


if __name__ == "__main__":
    _, summary_df, comparison_df = run_quantitative_benchmark(
        loss_rates=[0, 5, 8, 15],
        initial_ssthresh_list=[16],
        total_rounds=20,
        num_trials=30,
        base_seed=42,
    )

    print("=== [1] 조건별 평균 요약 (benchmark_summary.csv) ===")
    print(summary_df.to_string(index=False))
    print("\n=== [2] Tahoe vs Reno 정량 비교표 (benchmark_tahoe_vs_reno.csv) ===")
    print(comparison_df.to_string(index=False))
