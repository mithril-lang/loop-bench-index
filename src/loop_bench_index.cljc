(ns loop-bench-index)

(def format "https://mithril.fund/bench-index/cohort-v1")

(defn validate-report [report]
  (when-not (and (map? report)
                 (= "https://mithril.fund/bench/agent-loop-plan-v2" (:format report))
                 (map? (:models report))
                 (= #{:hermes :mithril} (set (keys (:models report))))
                 (contains? #{:stack :same-model} (:comparison-mode report))
                 (integer? (:runs report))
                 (integer? (:successful-runs report))
                 (map? (:paired-comparison report)))
    (throw (ex-info "benchmark report is missing identity or paired measurements"
                    {:index/error :invalid-report})))
  report)

(defn- lane-row [report receipts lane]
  (let [runs (filter #(= lane (:lane %)) receipts)]
    {:requested-model (get-in report [:models lane])
     :resolved-models (vec (sort (distinct (keep :model runs))))
     :runs (count runs)
     :successful-runs (count (filter :success? runs))}))

(defn index-row
  ([report] (index-row report {}))
  ([report {:keys [receipts runner-revision]}]
   (validate-report report)
   (let [comparison (:paired-comparison report)
         receipts (or receipts [])]
     {:format format
      :corpus-id (:corpus-id report)
      :corpus-digest (:corpus-digest report)
      :runner-revision runner-revision
      :lanes {:hermes (lane-row report receipts :hermes)
              :mithril (lane-row report receipts :mithril)}
      :comparison-mode (:comparison-mode report)
      :runs (:runs report)
      :successful-runs (:successful-runs report)
      :paired-runs (:cases comparison)
      :comparable-pairs (:comparable-cases comparison)
      :equivalent-pairs (:equivalent-cases comparison)
      :equivalence-coverage (:equivalence-coverage comparison)
      :indices (:indices comparison)})))
