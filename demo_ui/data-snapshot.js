export const snapshotData = {
  meta: {
    source: "snapshot",
    note: "未读取到仓库中的实时 JSON，当前展示内置结果快照。建议在仓库根目录启动本地静态服务后访问 /demo_ui/。",
  },
  groups: {
    group1: {
      id: "group1",
      title: "Group 1",
      subtitle: "Titanic 单表统计",
      description:
        "以 Titanic 为主的单表统计型任务，当前是 CodeAct 表现最稳定的一组，适合展示 generic CSV 路由与稳定落答案的效果。",
      datasets: ["Titanic.csv"],
      fullAgent: {
        text: {
          accuracy: { total_correct: 9, total_fields: 10, overall_accuracy: 0.9 },
          metrics: {
            llm_calls: 70,
            input_tokens: 123895,
            output_tokens: 20638,
            total_tokens: 144533,
            context_original_chars: 0,
            context_compressed_chars: 0,
            context_saved_chars: 0,
          },
          stats: {
            total_rounds: 10,
            total_duration_s: 850.09,
            avg_duration_s: 85.01,
            min_duration_s: 72.55,
            max_duration_s: 99.98,
          },
          per_round: [
            {
              round: 1,
              question: "Calculate the mean and standard deviation of the fare paid by the passengers.",
              correct: 1,
              total: 1,
              duration_s: 86.05,
              details: [{ field: "std_dev_fare", extracted: "49.67", gold: "49.67", match: true }],
            },
            {
              round: 9,
              question:
                "Calculate the Pearson correlation coefficient between the age and fare variables for passengers who survived and were in first class.",
              correct: 0,
              total: 1,
              duration_s: 91.2,
              details: [{ field: "correlation_coefficient", extracted: "-0.046", gold: "-0.123", match: false }],
            },
            {
              round: 10,
              question:
                "Create a new feature called 'FamilySize' and find the correlation coefficient between 'FamilySize' and 'Survived'.",
              correct: 1,
              total: 1,
              duration_s: 99.98,
              details: [{ field: "correlation_coefficient", extracted: "0.02", gold: "0.02", match: true }],
            },
          ],
        },
        structured: {
          accuracy: { total_correct: 10, total_fields: 10, overall_accuracy: 1 },
          metrics: {
            llm_calls: 70,
            input_tokens: 108173,
            output_tokens: 19505,
            total_tokens: 127678,
            context_original_chars: 105130,
            context_compressed_chars: 41436,
            context_saved_chars: 63694,
          },
          stats: {
            total_rounds: 10,
            total_duration_s: 827.62,
            avg_duration_s: 82.76,
            min_duration_s: 63.43,
            max_duration_s: 108.1,
          },
          per_round: [
            {
              round: 1,
              question: "Calculate the mean and standard deviation of the fare paid by the passengers.",
              correct: 1,
              total: 1,
              duration_s: 80.08,
              details: [{ field: "std_dev_fare", extracted: "49.67", gold: "49.67", match: true }],
            },
            {
              round: 9,
              question:
                "Calculate the Pearson correlation coefficient between the age and fare variables for passengers who survived and were in first class.",
              correct: 1,
              total: 1,
              duration_s: 84.94,
              details: [{ field: "correlation_coefficient", extracted: "-0.123", gold: "-0.123", match: true }],
            },
            {
              round: 10,
              question:
                "Create a new feature called 'FamilySize' and find the correlation coefficient between 'FamilySize' and 'Survived'.",
              correct: 1,
              total: 1,
              duration_s: 108.1,
              details: [{ field: "correlation_coefficient", extracted: "0.02", gold: "0.02", match: true }],
            },
          ],
        },
      },
      codeactOnly: {
        accuracy: { total_correct: 10, total_fields: 10, overall_accuracy: 1 },
        metrics: { llm_calls: 10, input_tokens: 30191, output_tokens: 1132, total_tokens: 31323 },
        stats: { total_duration_s: 81.48, avg_duration_s: 8.15, total_rounds: 10 },
        spotlightRound: {
          round: 1,
          question: "Calculate the mean and standard deviation of the fare paid by the passengers.",
          final_answer: "@mean_fare[32.20] @std_dev_fare[49.67]",
          execution_summary: "CodeAct execution succeeded via llm_generate with metrics: {}",
          execution_code:
            "rows = load_csv_rows()\\nfares = numeric_values(rows, \"Fare\")\\nextracted_answers[\"mean_fare\"] = f\"{mean(fares):.2f}\"\\nextracted_answers[\"std_dev_fare\"] = f\"{std(fares):.2f}\"",
          execution_trace: [
            {
              stage: "codeact.route",
              route: "generic_csv_question",
              kind: "table_csv",
              reason: "CSV artifact detected; use generic CSV reasoning only.",
              required_fields: ["mean_fare", "std_dev_fare"],
              artifact_count: 1,
            },
            {
              stage: "codeact.runtime",
              ok: true,
              duration_s: 0.0113,
              error: "",
              missing_required_fields: [],
              selected_strategy: "llm_generate",
            },
          ],
          execution_result: { selected_strategy: "llm_generate", error: "" },
        },
      },
    },
    group2: {
      id: "group2",
      title: "Group 2",
      subtitle: "疫情与气象混合任务",
      description:
        "当前简化版 Group 2 既包含缺失值、相关系数，也包含带条件过滤和 outlier replacement 的较难问题，适合展示 structured 对 token 的压缩收益。",
      datasets: ["WHO Region cases", "Weather.csv"],
      fullAgent: {
        text: {
          accuracy: { total_correct: 14, total_fields: 17, overall_accuracy: 0.8235 },
          metrics: {
            llm_calls: 86,
            input_tokens: 173178,
            output_tokens: 25308,
            total_tokens: 198486,
            context_original_chars: 0,
            context_compressed_chars: 0,
            context_saved_chars: 0,
          },
          stats: {
            total_rounds: 12,
            total_duration_s: 1660.36,
            avg_duration_s: 138.36,
            min_duration_s: 107.74,
            max_duration_s: 203.67,
          },
          per_round: [
            {
              round: 5,
              question:
                "Among the countries whose \"WHO Region\" value is exactly \"Americas\", which country has the highest average number of cases recorded over the years?",
              correct: 0,
              total: 1,
              duration_s: 145.67,
              details: [{ field: "country_name", extracted: "", gold: "Congo", match: false }],
            },
            {
              round: 9,
              question: "How many missing values are there in the WINDSPEED, AT, and RELHUM columns?",
              correct: 3,
              total: 3,
              duration_s: 113.54,
              details: [
                { field: "missing_windspeed", extracted: "594", gold: "594", match: true },
                { field: "missing_at", extracted: "590", gold: "590", match: true },
                { field: "missing_relhum", extracted: "8736", gold: "8736", match: true },
              ],
            },
            {
              round: 12,
              question: "What are the mean wind speeds before and after replacing outlier wind speeds?",
              correct: 0,
              total: 2,
              duration_s: 203.67,
              details: [
                { field: "mean_wind_pre", extracted: "", gold: "5.98", match: false },
                { field: "mean_wind_post", extracted: "", gold: "5.85", match: false },
              ],
            },
          ],
        },
        structured: {
          accuracy: { total_correct: 15, total_fields: 17, overall_accuracy: 0.8824 },
          metrics: {
            llm_calls: 85,
            input_tokens: 150176,
            output_tokens: 24588,
            total_tokens: 174764,
            context_original_chars: 128140,
            context_compressed_chars: 48638,
            context_saved_chars: 79502,
          },
          stats: {
            total_rounds: 12,
            total_duration_s: 1584.89,
            avg_duration_s: 132.07,
            min_duration_s: 100.94,
            max_duration_s: 165.11,
          },
          per_round: [
            {
              round: 5,
              question:
                "Among the countries whose \"WHO Region\" value is exactly \"Americas\", which country has the highest average number of cases recorded over the years?",
              correct: 1,
              total: 1,
              duration_s: 122.2,
              details: [{ field: "country_name", extracted: "Congo", gold: "Congo", match: true }],
            },
            {
              round: 9,
              question: "How many missing values are there in the WINDSPEED, AT, and RELHUM columns?",
              correct: 3,
              total: 3,
              duration_s: 111.89,
              details: [
                { field: "missing_windspeed", extracted: "594", gold: "594", match: true },
                { field: "missing_at", extracted: "590", gold: "590", match: true },
                { field: "missing_relhum", extracted: "8736", gold: "8736", match: true },
              ],
            },
            {
              round: 12,
              question: "What are the mean wind speeds before and after replacing outlier wind speeds?",
              correct: 0,
              total: 2,
              duration_s: 140.78,
              details: [
                { field: "mean_wind_pre", extracted: "", gold: "5.98", match: false },
                { field: "mean_wind_post", extracted: "", gold: "5.85", match: false },
              ],
            },
          ],
        },
      },
      codeactOnly: {
        accuracy: { total_correct: 16, total_fields: 17, overall_accuracy: 0.9412 },
        metrics: { llm_calls: 13, input_tokens: 44000, output_tokens: 2039, total_tokens: 46039 },
        stats: { total_duration_s: 322.02, avg_duration_s: 26.83, total_rounds: 12 },
        spotlightRound: {
          round: 5,
          question:
            "Among the countries whose \"WHO Region\" value is exactly \"Americas\", which country has the highest average number of cases recorded over the years?",
          final_answer: "",
          execution_summary:
            "CodeAct execution failed: ValueError: Unsafe CodeAct node: arguments; Missing required CodeAct answer fields: ['country_name'] (generic CSV route)",
          execution_code:
            "americas_rows = [row for row in rows if row[\"WHO Region\"] == \"Americas\"]\\nmax_avg_country = max(country_data, key=lambda k: mean(country_data[k]))\\nextracted_answers[\"country_name\"] = max_avg_country",
          execution_trace: [
            {
              stage: "codeact.route",
              route: "generic_csv_question",
              kind: "table_csv",
              reason: "CSV artifact detected; use generic CSV reasoning only.",
              required_fields: ["country_name"],
              artifact_count: 1,
            },
            {
              stage: "codeact.runtime",
              ok: false,
              duration_s: 0.0008,
              error: "ValueError: Unsafe CodeAct node: arguments",
              missing_required_fields: ["country_name"],
              selected_strategy: "llm_repair",
            },
          ],
          execution_result: {
            selected_strategy: "llm_repair",
            error: "ValueError: Unsafe CodeAct node: arguments; Missing required CodeAct answer fields: ['country_name']",
          },
        },
      },
    },
    group3: {
      id: "group3",
      title: "Group 3",
      subtitle: "信用与酒店评论语义任务",
      description:
        "Group 3 里包含更强的语义抽象和实体级选择，能够明显看出 CodeAct 与上游 analyst 的职责边界，也是后续扩展创新最需要保留窗口的一组。",
      datasets: ["Credit.csv", "Hotels.csv"],
      fullAgent: {
        text: {
          accuracy: { total_correct: 13, total_fields: 15, overall_accuracy: 0.8667 },
          metrics: {
            llm_calls: 77,
            input_tokens: 125866,
            output_tokens: 22008,
            total_tokens: 147874,
            context_original_chars: 0,
            context_compressed_chars: 0,
            context_saved_chars: 0,
          },
          stats: {
            total_rounds: 11,
            total_duration_s: 1214.13,
            avg_duration_s: 110.38,
            min_duration_s: 90.61,
            max_duration_s: 138.55,
          },
          per_round: [
            {
              round: 1,
              question: "Calculate the mean and standard deviation of the \"Income\" column in the Credit.csv file.",
              correct: 1,
              total: 2,
              duration_s: 104.32,
              details: [
                { field: "mean_income", extracted: "45.22", gold: "45.22", match: true },
                { field: "std_dev_income", extracted: "35.20", gold: "35.24", match: false },
              ],
            },
            {
              round: 9,
              question:
                "2. Among the hotels with a star rating, what is the correlation between reviews and bubble score?",
              correct: 3,
              total: 3,
              duration_s: 138.55,
              details: [
                { field: "above4_correlation", extracted: "-0.28", gold: "-0.28", match: true },
                { field: "below3_correlation", extracted: "0.15", gold: "0.15", match: true },
                { field: "between3and4_correlation", extracted: "0.04", gold: "0.04", match: true },
              ],
            },
            {
              round: 11,
              question:
                "3. What is the average review count for hotels in each city? Are there any cities where the average review count is significantly higher or lower compared to the overall average review count of all hotels?",
              correct: 1,
              total: 2,
              duration_s: 111.49,
              details: [
                { field: "lower_city_count", extracted: "6", gold: "4", match: false },
                { field: "higher_city_count", extracted: "0", gold: "0", match: true },
              ],
            },
          ],
        },
        structured: {
          accuracy: { total_correct: 12, total_fields: 15, overall_accuracy: 0.8 },
          metrics: {
            llm_calls: 79,
            input_tokens: 115145,
            output_tokens: 23086,
            total_tokens: 138231,
            context_original_chars: 121654,
            context_compressed_chars: 45654,
            context_saved_chars: 76000,
          },
          stats: {
            total_rounds: 11,
            total_duration_s: 1443.36,
            avg_duration_s: 131.21,
            min_duration_s: 90.53,
            max_duration_s: 208.06,
          },
          per_round: [
            {
              round: 1,
              question: "Calculate the mean and standard deviation of the \"Income\" column in the Credit.csv file.",
              correct: 1,
              total: 2,
              duration_s: 111.75,
              details: [
                { field: "mean_income", extracted: "45.22", gold: "45.22", match: true },
                { field: "std_dev_income", extracted: "35.20", gold: "35.24", match: false },
              ],
            },
            {
              round: 10,
              question: "2. Which hotel brand has the highest average star rating among hotels with at least 100 reviews?",
              correct: 0,
              total: 1,
              duration_s: 164.76,
              details: [
                {
                  field: "brand_with_highest_average_star_rating",
                  extracted: "",
                  gold: "Preferred Hotels & Resorts",
                  match: false,
                },
              ],
            },
            {
              round: 11,
              question:
                "3. What is the average review count for hotels in each city? Are there any cities where the average review count is significantly higher or lower compared to the overall average review count of all hotels?",
              correct: 1,
              total: 2,
              duration_s: 105.91,
              details: [
                { field: "lower_city_count", extracted: "7", gold: "4", match: false },
                { field: "higher_city_count", extracted: "0", gold: "0", match: true },
              ],
            },
          ],
        },
      },
      codeactOnly: {
        accuracy: { total_correct: 10, total_fields: 15, overall_accuracy: 0.6667 },
        metrics: { llm_calls: 12, input_tokens: 33969, output_tokens: 2176, total_tokens: 36145 },
        stats: { total_duration_s: 139.43, avg_duration_s: 12.68, total_rounds: 11 },
        spotlightRound: {
          round: 9,
          question:
            "2. Among the hotels with a star rating, what is the correlation between the number of reviews a hotel has received and its bubble score?",
          final_answer: "@below3_correlation[0.37] @between3and4_correlation[0.16] @above4_correlation[0.28]",
          execution_summary: "CodeAct execution succeeded via llm_repair with metrics: {}",
          execution_code:
            "filtered_rows = [row for row in rows if row[\"star_rating\"] != \"\" and row[\"bubble_score\"] != \"\"]\\nfor row in filtered_rows:\\n    rating = to_float(row[\"star_rating\"])\\n    score = to_float(row[\"bubble_score\"])\\n    ...\\nbelow3_corr = pearson_corr(below3)",
          execution_trace: [
            {
              stage: "codeact.route",
              route: "generic_csv_question",
              kind: "table_csv",
              reason: "CSV artifact detected; use generic CSV reasoning only.",
              required_fields: ["below3_correlation", "between3and4_correlation", "above4_correlation"],
              artifact_count: 1,
            },
            {
              stage: "codeact.runtime",
              ok: true,
              duration_s: 0.0166,
              error: "",
              missing_required_fields: [],
              selected_strategy: "llm_repair",
            },
          ],
          execution_result: { selected_strategy: "llm_repair", error: "" },
        },
      },
    },
  },
};
