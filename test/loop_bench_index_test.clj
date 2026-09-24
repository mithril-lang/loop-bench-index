(ns loop-bench-index-test
  (:require [clojure.test :refer [deftest is testing]]
            [loop-bench-index :as index]))

(def report
  {:format "https://mithril.fund/bench/agent-loop-plan-v2"
   :corpus-id "fixture"
   :models {:hermes "chat/model" :mithril "decision/model"}
   :comparison-mode :stack
   :runs 6 :successful-runs 5
   :paired-comparison {:cases 3 :comparable-cases 3
                       :equivalent-cases 2 :equivalence-coverage 2/3
                       :indices {:tokens 25 :cost-usd 30}}})

(deftest index-keeps-models-coverage-and-parity-qualified-indices
  (let [row (index/index-row report)]
    (is (= :stack (:comparison-mode row)))
    (is (= 2/3 (:equivalence-coverage row)))
    (is (= 2 (:equivalent-pairs row)))
    (is (= {:tokens 25 :cost-usd 30} (:indices row)))))

(deftest invalid-report-is-refused
  (testing "reports without lane identities cannot become index rows"
    (is (= :invalid-report
           (try (index/index-row (dissoc report :models)) nil
                (catch clojure.lang.ExceptionInfo e
                  (:index/error (ex-data e)))))))
