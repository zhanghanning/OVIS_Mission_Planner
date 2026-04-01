#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace {

constexpr double kEpsilon = 1e-9;
constexpr const char* kNoError = "";

thread_local std::string g_last_error;

struct NativePlannerInput {
  int32_t robot_count;
  int32_t target_count;
  const double* budgets_m;
  const uint8_t* start_reachable;
  const double* start_distance_m;
  const double* start_time_s;
  const uint8_t* home_reachable;
  const double* home_distance_m;
  const double* home_time_s;
  const uint8_t* pair_reachable;
  const double* pair_distance_m;
  const double* pair_time_s;
  int32_t max_improvement_passes;
};

struct NativePlannerOutput {
  int32_t* route_lengths;
  int32_t* routes_flat;
  uint8_t* unassigned_mask;
};

struct Metric {
  bool reachable = true;
  double distance_m = 0.0;
  double estimated_time_s = 0.0;
};

struct Score {
  std::vector<double> time_vector;
  double total_distance_m = 0.0;
};

struct StateEntry {
  double budget_m = 0.0;
  std::vector<int> route;
  Metric metrics;
};

struct Insertion {
  std::vector<int> route;
  Metric metrics;
  int position = 0;
};

struct Option {
  int robot_id = 0;
  std::vector<int> route;
  Metric metrics;
  Score score;
};

struct Choice {
  int target_id = 0;
  int option_count = 0;
  double regret = 0.0;
  double difficulty = 0.0;
  Option option;
};

struct RepairMove {
  int target_id = 0;
  int source_robot_id = 0;
  int target_robot_id = 0;
  int displaced_target = 0;
  double difficulty = 0.0;
  std::vector<int> source_route;
  std::vector<int> target_route;
  Metric source_metrics;
  Metric target_metrics;
  Score score;
};

struct RelocateMove {
  int source_robot_id = 0;
  int target_robot_id = 0;
  std::vector<int> source_route;
  std::vector<int> target_route;
  Metric source_metrics;
  Metric target_metrics;
};

struct SwapMove {
  int left_robot_id = 0;
  int right_robot_id = 0;
  std::vector<int> left_route;
  std::vector<int> right_route;
  Metric left_metrics;
  Metric right_metrics;
};

enum class ConstructionMode {
  kRegret,
  kConstrained,
  kBestGlobal,
};

double round3(double value) {
  return std::round(value * 1000.0) / 1000.0;
}

bool float_less(double left, double right) {
  return left + kEpsilon < right;
}

bool float_greater(double left, double right) {
  return right + kEpsilon < left;
}

int compare_time_vectors(const std::vector<double>& left, const std::vector<double>& right) {
  const std::size_t limit = std::min(left.size(), right.size());
  for (std::size_t index = 0; index < limit; ++index) {
    if (float_less(left[index], right[index])) {
      return -1;
    }
    if (float_greater(left[index], right[index])) {
      return 1;
    }
  }
  if (left.size() < right.size()) {
    return -1;
  }
  if (left.size() > right.size()) {
    return 1;
  }
  return 0;
}

int compare_scores(const Score& left, const Score& right) {
  const int vector_cmp = compare_time_vectors(left.time_vector, right.time_vector);
  if (vector_cmp != 0) {
    return vector_cmp;
  }
  if (float_less(left.total_distance_m, right.total_distance_m)) {
    return -1;
  }
  if (float_greater(left.total_distance_m, right.total_distance_m)) {
    return 1;
  }
  return 0;
}

bool score_better(const Score& candidate, const Score& incumbent) {
  return compare_scores(candidate, incumbent) < 0;
}

Score score_from_metrics(const std::vector<Metric>& metrics) {
  Score score;
  score.time_vector.reserve(metrics.size());
  for (const Metric& metric : metrics) {
    score.time_vector.push_back(metric.estimated_time_s);
    score.total_distance_m += metric.distance_m;
  }
  std::sort(score.time_vector.begin(), score.time_vector.end(), std::greater<double>());
  return score;
}

int start_index(const NativePlannerInput& input, int robot_id, int target_id) {
  return robot_id * input.target_count + target_id;
}

int pair_index(const NativePlannerInput& input, int source_target_id, int target_id) {
  return source_target_id * input.target_count + target_id;
}

Metric route_metrics(const NativePlannerInput& input, int robot_id, const std::vector<int>& route) {
  if (route.empty()) {
    return Metric{};
  }

  const int first_leg_index = start_index(input, robot_id, route.front());
  if (input.start_reachable[first_leg_index] == 0) {
    return Metric{false, 0.0, 0.0};
  }

  double total_distance_m = input.start_distance_m[first_leg_index];
  double total_time_s = input.start_time_s[first_leg_index];

  for (std::size_t index = 0; index + 1 < route.size(); ++index) {
    const int leg_index = pair_index(input, route[index], route[index + 1]);
    if (input.pair_reachable[leg_index] == 0) {
      return Metric{false, 0.0, 0.0};
    }
    total_distance_m += input.pair_distance_m[leg_index];
    total_time_s += input.pair_time_s[leg_index];
  }

  const int last_leg_index = start_index(input, robot_id, route.back());
  if (input.home_reachable[last_leg_index] == 0) {
    return Metric{false, 0.0, 0.0};
  }

  total_distance_m += input.home_distance_m[last_leg_index];
  total_time_s += input.home_time_s[last_leg_index];

  return Metric{true, round3(total_distance_m), round3(total_time_s)};
}

std::vector<StateEntry> build_state(const NativePlannerInput& input) {
  std::vector<StateEntry> state(static_cast<std::size_t>(input.robot_count));
  for (int robot_id = 0; robot_id < input.robot_count; ++robot_id) {
    state[robot_id].budget_m = input.budgets_m[robot_id];
    state[robot_id].metrics = Metric{};
  }
  return state;
}

Score state_score(const std::vector<StateEntry>& state, const std::vector<int>& robot_ids) {
  std::vector<Metric> metrics;
  metrics.reserve(robot_ids.size());
  for (int robot_id : robot_ids) {
    metrics.push_back(state[robot_id].metrics);
  }
  return score_from_metrics(metrics);
}

bool final_solution_better(
    int candidate_assigned_count,
    const Score& candidate_score,
    int incumbent_assigned_count,
    const std::optional<Score>& incumbent_score) {
  if (candidate_assigned_count != incumbent_assigned_count) {
    return candidate_assigned_count > incumbent_assigned_count;
  }
  if (!incumbent_score.has_value()) {
    return true;
  }
  return score_better(candidate_score, *incumbent_score);
}

bool route_sort_better(
    const Metric& candidate_metrics,
    const std::vector<int>& candidate_route,
    int candidate_position,
    int candidate_target,
    const Metric& incumbent_metrics,
    const std::vector<int>& incumbent_route,
    int incumbent_position,
    int incumbent_target) {
  if (float_less(candidate_metrics.estimated_time_s, incumbent_metrics.estimated_time_s)) {
    return true;
  }
  if (float_greater(candidate_metrics.estimated_time_s, incumbent_metrics.estimated_time_s)) {
    return false;
  }
  if (float_less(candidate_metrics.distance_m, incumbent_metrics.distance_m)) {
    return true;
  }
  if (float_greater(candidate_metrics.distance_m, incumbent_metrics.distance_m)) {
    return false;
  }
  if (candidate_route.size() != incumbent_route.size()) {
    return candidate_route.size() < incumbent_route.size();
  }
  if (candidate_position != incumbent_position) {
    return candidate_position < incumbent_position;
  }
  return candidate_target < incumbent_target;
}

std::optional<Insertion> best_insertion_for_candidate(
    const NativePlannerInput& input,
    int robot_id,
    const std::vector<int>& route,
    int candidate_target,
    double budget_m) {
  std::optional<Insertion> best;
  for (std::size_t position = 0; position <= route.size(); ++position) {
    std::vector<int> candidate_route = route;
    candidate_route.insert(candidate_route.begin() + static_cast<std::ptrdiff_t>(position), candidate_target);

    Metric metrics = route_metrics(input, robot_id, candidate_route);
    if (!metrics.reachable || float_greater(metrics.distance_m, budget_m)) {
      continue;
    }

    if (!best.has_value() ||
        route_sort_better(
            metrics,
            candidate_route,
            static_cast<int>(position),
            candidate_target,
            best->metrics,
            best->route,
            best->position,
            candidate_target)) {
      best = Insertion{candidate_route, metrics, static_cast<int>(position)};
    }
  }
  return best;
}

std::pair<std::vector<int>, Metric> two_opt_improve(
    const NativePlannerInput& input,
    int robot_id,
    const std::vector<int>& route,
    double budget_m) {
  std::vector<int> best_route = route;
  Metric best_metrics = route_metrics(input, robot_id, best_route);
  if (best_route.size() < 4 || !best_metrics.reachable) {
    return {best_route, best_metrics};
  }

  bool improved = true;
  while (improved) {
    improved = false;
    for (std::size_t left = 0; left + 2 < best_route.size() && !improved; ++left) {
      for (std::size_t right = left + 2; right <= best_route.size(); ++right) {
        std::vector<int> candidate_route = best_route;
        std::reverse(
            candidate_route.begin() + static_cast<std::ptrdiff_t>(left),
            candidate_route.begin() + static_cast<std::ptrdiff_t>(right));

        Metric candidate_metrics = route_metrics(input, robot_id, candidate_route);
        if (!candidate_metrics.reachable || float_greater(candidate_metrics.distance_m, budget_m)) {
          continue;
        }

        const bool better_time = float_less(candidate_metrics.estimated_time_s, best_metrics.estimated_time_s);
        const bool equal_or_better_time =
            !float_greater(candidate_metrics.estimated_time_s, best_metrics.estimated_time_s);
        const bool better_distance = float_less(candidate_metrics.distance_m, best_metrics.distance_m);
        if (better_time || (equal_or_better_time && better_distance)) {
          best_route = std::move(candidate_route);
          best_metrics = candidate_metrics;
          improved = true;
          break;
        }
      }
    }
  }

  return {best_route, best_metrics};
}

void optimize_specific_routes(
    const NativePlannerInput& input,
    std::vector<StateEntry>& state,
    const std::vector<int>& robot_ids) {
  std::set<int> unique_robot_ids(robot_ids.begin(), robot_ids.end());
  for (int robot_id : unique_robot_ids) {
    const auto [route, metrics] = two_opt_improve(input, robot_id, state[robot_id].route, state[robot_id].budget_m);
    state[robot_id].route = route;
    state[robot_id].metrics = metrics;
  }
}

std::pair<double, int> singleton_target_difficulty(
    const NativePlannerInput& input,
    const std::vector<StateEntry>& state,
    int target_id) {
  double best_time = std::numeric_limits<double>::infinity();
  int feasible_robot_count = 0;
  std::vector<int> singleton_route = {target_id};
  for (int robot_id = 0; robot_id < input.robot_count; ++robot_id) {
    Metric metrics = route_metrics(input, robot_id, singleton_route);
    if (!metrics.reachable || float_greater(metrics.distance_m, state[robot_id].budget_m)) {
      continue;
    }
    ++feasible_robot_count;
    best_time = std::min(best_time, metrics.estimated_time_s);
  }
  return {best_time, feasible_robot_count};
}

bool option_sort_better(const Option& candidate, const Option& incumbent) {
  const int score_cmp = compare_scores(candidate.score, incumbent.score);
  if (score_cmp != 0) {
    return score_cmp < 0;
  }
  if (float_less(candidate.metrics.estimated_time_s, incumbent.metrics.estimated_time_s)) {
    return true;
  }
  if (float_greater(candidate.metrics.estimated_time_s, incumbent.metrics.estimated_time_s)) {
    return false;
  }
  if (float_less(candidate.metrics.distance_m, incumbent.metrics.distance_m)) {
    return true;
  }
  if (float_greater(candidate.metrics.distance_m, incumbent.metrics.distance_m)) {
    return false;
  }
  return candidate.robot_id < incumbent.robot_id;
}

std::vector<Option> evaluate_target_options(
    const NativePlannerInput& input,
    const std::vector<StateEntry>& state,
    const std::vector<int>& robot_ids,
    int target_id) {
  std::vector<Option> options;
  options.reserve(robot_ids.size());

  for (int robot_id : robot_ids) {
    const auto insertion =
        best_insertion_for_candidate(input, robot_id, state[robot_id].route, target_id, state[robot_id].budget_m);
    if (!insertion.has_value()) {
      continue;
    }

    std::vector<Metric> metrics_after;
    metrics_after.reserve(robot_ids.size());
    for (int current_robot_id : robot_ids) {
      metrics_after.push_back(current_robot_id == robot_id ? insertion->metrics : state[current_robot_id].metrics);
    }

    options.push_back(Option{
        robot_id,
        insertion->route,
        insertion->metrics,
        score_from_metrics(metrics_after),
    });
  }

  std::sort(
      options.begin(),
      options.end(),
      [](const Option& left, const Option& right) { return option_sort_better(left, right); });
  return options;
}

bool choice_better(const Choice& candidate, const Choice& incumbent, ConstructionMode mode) {
  if (mode == ConstructionMode::kRegret) {
    if (candidate.option_count != incumbent.option_count) {
      return candidate.option_count < incumbent.option_count;
    }
    if (float_greater(candidate.regret, incumbent.regret)) {
      return true;
    }
    if (float_less(candidate.regret, incumbent.regret)) {
      return false;
    }
    if (float_greater(candidate.difficulty, incumbent.difficulty)) {
      return true;
    }
    if (float_less(candidate.difficulty, incumbent.difficulty)) {
      return false;
    }
    if (option_sort_better(candidate.option, incumbent.option)) {
      return true;
    }
    if (option_sort_better(incumbent.option, candidate.option)) {
      return false;
    }
    return candidate.target_id < incumbent.target_id;
  }

  if (mode == ConstructionMode::kConstrained) {
    if (candidate.option_count != incumbent.option_count) {
      return candidate.option_count < incumbent.option_count;
    }
    if (float_greater(candidate.difficulty, incumbent.difficulty)) {
      return true;
    }
    if (float_less(candidate.difficulty, incumbent.difficulty)) {
      return false;
    }
    if (option_sort_better(candidate.option, incumbent.option)) {
      return true;
    }
    if (option_sort_better(incumbent.option, candidate.option)) {
      return false;
    }
    return candidate.target_id < incumbent.target_id;
  }

  if (option_sort_better(candidate.option, incumbent.option)) {
    return true;
  }
  if (option_sort_better(incumbent.option, candidate.option)) {
    return false;
  }
  if (candidate.option_count != incumbent.option_count) {
    return candidate.option_count < incumbent.option_count;
  }
  if (float_greater(candidate.difficulty, incumbent.difficulty)) {
    return true;
  }
  if (float_less(candidate.difficulty, incumbent.difficulty)) {
    return false;
  }
  return candidate.target_id < incumbent.target_id;
}

std::optional<Choice> select_next_assignment(
    const NativePlannerInput& input,
    const std::vector<StateEntry>& state,
    const std::set<int>& unassigned,
    const std::vector<int>& robot_ids,
    const std::vector<double>& difficulty_by_target,
    ConstructionMode mode) {
  std::optional<Choice> best_choice;

  for (int target_id : unassigned) {
    const std::vector<Option> options = evaluate_target_options(input, state, robot_ids, target_id);
    if (options.empty()) {
      continue;
    }

    const Option& best_option = options.front();
    const Option* second_option = options.size() > 1 ? &options[1] : nullptr;
    const double best_makespan = best_option.score.time_vector.empty() ? 0.0 : best_option.score.time_vector.front();
    const double second_makespan =
        second_option == nullptr || second_option->score.time_vector.empty()
            ? std::numeric_limits<double>::infinity()
            : second_option->score.time_vector.front();
    const double regret = second_option == nullptr ? std::numeric_limits<double>::infinity()
                                                   : second_makespan - best_makespan;

    Choice choice;
    choice.target_id = target_id;
    choice.option_count = static_cast<int>(options.size());
    choice.regret = regret;
    choice.difficulty = difficulty_by_target[target_id];
    choice.option = best_option;

    if (!best_choice.has_value() || choice_better(choice, *best_choice, mode)) {
      best_choice = choice;
    }
  }

  return best_choice;
}

bool assign_remaining_targets(
    const NativePlannerInput& input,
    std::vector<StateEntry>& state,
    std::set<int>& unassigned,
    const std::vector<int>& robot_ids,
    const std::vector<double>& difficulty_by_target,
    ConstructionMode mode) {
  bool progress = false;
  while (!unassigned.empty()) {
    const auto choice = select_next_assignment(input, state, unassigned, robot_ids, difficulty_by_target, mode);
    if (!choice.has_value()) {
      break;
    }

    const Option& option = choice->option;
    state[option.robot_id].route = option.route;
    state[option.robot_id].metrics = option.metrics;
    unassigned.erase(choice->target_id);
    progress = true;
  }
  return progress;
}

bool repair_move_better(const RepairMove& candidate, const RepairMove& incumbent) {
  const int score_cmp = compare_scores(candidate.score, incumbent.score);
  if (score_cmp != 0) {
    return score_cmp < 0;
  }
  if (float_greater(candidate.difficulty, incumbent.difficulty)) {
    return true;
  }
  if (float_less(candidate.difficulty, incumbent.difficulty)) {
    return false;
  }
  if (candidate.target_id != incumbent.target_id) {
    return candidate.target_id < incumbent.target_id;
  }
  if (candidate.source_robot_id != incumbent.source_robot_id) {
    return candidate.source_robot_id < incumbent.source_robot_id;
  }
  if (candidate.target_robot_id != incumbent.target_robot_id) {
    return candidate.target_robot_id < incumbent.target_robot_id;
  }
  return candidate.displaced_target < incumbent.displaced_target;
}

bool repair_unassigned_by_relocation(
    const NativePlannerInput& input,
    std::vector<StateEntry>& state,
    std::set<int>& unassigned,
    const std::vector<int>& robot_ids,
    const std::vector<double>& difficulty_by_target) {
  bool improved = false;

  while (!unassigned.empty()) {
    std::optional<RepairMove> best_move;

    std::vector<int> ordered_unassigned(unassigned.begin(), unassigned.end());
    std::sort(
        ordered_unassigned.begin(),
        ordered_unassigned.end(),
        [&difficulty_by_target](int left, int right) {
          if (float_greater(difficulty_by_target[left], difficulty_by_target[right])) {
            return true;
          }
          if (float_less(difficulty_by_target[left], difficulty_by_target[right])) {
            return false;
          }
          return left < right;
        });

    for (int target_id : ordered_unassigned) {
      for (int source_robot_id : robot_ids) {
        const std::vector<int> source_route = state[source_robot_id].route;
        for (std::size_t source_index = 0; source_index < source_route.size(); ++source_index) {
          const int displaced_target = source_route[source_index];

          std::vector<int> reduced_source_route = source_route;
          reduced_source_route.erase(reduced_source_route.begin() + static_cast<std::ptrdiff_t>(source_index));

          const Metric reduced_source_metrics = route_metrics(input, source_robot_id, reduced_source_route);
          if (!reduced_source_metrics.reachable ||
              float_greater(reduced_source_metrics.distance_m, state[source_robot_id].budget_m)) {
            continue;
          }

          const auto target_insertion = best_insertion_for_candidate(
              input,
              source_robot_id,
              reduced_source_route,
              target_id,
              state[source_robot_id].budget_m);
          if (!target_insertion.has_value()) {
            continue;
          }

          for (int target_robot_id : robot_ids) {
            if (target_robot_id == source_robot_id) {
              continue;
            }

            const auto displaced_insertion = best_insertion_for_candidate(
                input,
                target_robot_id,
                state[target_robot_id].route,
                displaced_target,
                state[target_robot_id].budget_m);
            if (!displaced_insertion.has_value()) {
              continue;
            }

            std::vector<Metric> metrics_after;
            metrics_after.reserve(robot_ids.size());
            for (int robot_id : robot_ids) {
              if (robot_id == source_robot_id) {
                metrics_after.push_back(target_insertion->metrics);
              } else if (robot_id == target_robot_id) {
                metrics_after.push_back(displaced_insertion->metrics);
              } else {
                metrics_after.push_back(state[robot_id].metrics);
              }
            }

            RepairMove move;
            move.target_id = target_id;
            move.source_robot_id = source_robot_id;
            move.target_robot_id = target_robot_id;
            move.displaced_target = displaced_target;
            move.difficulty = difficulty_by_target[target_id];
            move.source_route = target_insertion->route;
            move.target_route = displaced_insertion->route;
            move.source_metrics = target_insertion->metrics;
            move.target_metrics = displaced_insertion->metrics;
            move.score = score_from_metrics(metrics_after);

            if (!best_move.has_value() || repair_move_better(move, *best_move)) {
              best_move = std::move(move);
            }
          }
        }
      }
    }

    if (!best_move.has_value()) {
      break;
    }

    state[best_move->source_robot_id].route = best_move->source_route;
    state[best_move->source_robot_id].metrics = best_move->source_metrics;
    state[best_move->target_robot_id].route = best_move->target_route;
    state[best_move->target_robot_id].metrics = best_move->target_metrics;
    optimize_specific_routes(input, state, {best_move->source_robot_id, best_move->target_robot_id});
    unassigned.erase(best_move->target_id);
    improved = true;
  }

  return improved;
}

bool relocate_improve(
    const NativePlannerInput& input,
    std::vector<StateEntry>& state,
    const std::vector<int>& robot_ids) {
  bool improved = false;

  while (true) {
    const Score current_score = state_score(state, robot_ids);
    Score best_score = current_score;
    std::optional<RelocateMove> best_move;

    for (int source_robot_id : robot_ids) {
      const std::vector<int> source_route = state[source_robot_id].route;
      for (std::size_t source_index = 0; source_index < source_route.size(); ++source_index) {
        const int target_id = source_route[source_index];

        std::vector<int> reduced_source_route = source_route;
        reduced_source_route.erase(reduced_source_route.begin() + static_cast<std::ptrdiff_t>(source_index));

        const Metric reduced_source_metrics = route_metrics(input, source_robot_id, reduced_source_route);
        if (!reduced_source_metrics.reachable ||
            float_greater(reduced_source_metrics.distance_m, state[source_robot_id].budget_m)) {
          continue;
        }

        for (int target_robot_id : robot_ids) {
          if (target_robot_id == source_robot_id) {
            continue;
          }

          const auto insertion = best_insertion_for_candidate(
              input,
              target_robot_id,
              state[target_robot_id].route,
              target_id,
              state[target_robot_id].budget_m);
          if (!insertion.has_value()) {
            continue;
          }

          std::vector<Metric> metrics_after;
          metrics_after.reserve(robot_ids.size());
          for (int robot_id : robot_ids) {
            if (robot_id == source_robot_id) {
              metrics_after.push_back(reduced_source_metrics);
            } else if (robot_id == target_robot_id) {
              metrics_after.push_back(insertion->metrics);
            } else {
              metrics_after.push_back(state[robot_id].metrics);
            }
          }

          const Score candidate_score = score_from_metrics(metrics_after);
          if (!score_better(candidate_score, best_score)) {
            continue;
          }

          best_score = candidate_score;
          best_move = RelocateMove{
              source_robot_id,
              target_robot_id,
              reduced_source_route,
              insertion->route,
              reduced_source_metrics,
              insertion->metrics,
          };
        }
      }
    }

    if (!best_move.has_value()) {
      break;
    }

    state[best_move->source_robot_id].route = best_move->source_route;
    state[best_move->source_robot_id].metrics = best_move->source_metrics;
    state[best_move->target_robot_id].route = best_move->target_route;
    state[best_move->target_robot_id].metrics = best_move->target_metrics;
    optimize_specific_routes(input, state, {best_move->source_robot_id, best_move->target_robot_id});
    improved = true;
  }

  return improved;
}

bool swap_improve(
    const NativePlannerInput& input,
    std::vector<StateEntry>& state,
    const std::vector<int>& robot_ids) {
  bool improved = false;

  while (true) {
    const Score current_score = state_score(state, robot_ids);
    Score best_score = current_score;
    std::optional<SwapMove> best_move;

    for (std::size_t left_index = 0; left_index < robot_ids.size(); ++left_index) {
      const int left_robot_id = robot_ids[left_index];
      const std::vector<int> left_route = state[left_robot_id].route;
      if (left_route.empty()) {
        continue;
      }

      for (std::size_t right_index = left_index + 1; right_index < robot_ids.size(); ++right_index) {
        const int right_robot_id = robot_ids[right_index];
        const std::vector<int> right_route = state[right_robot_id].route;
        if (right_route.empty()) {
          continue;
        }

        for (std::size_t left_task_index = 0; left_task_index < left_route.size(); ++left_task_index) {
          const int left_target = left_route[left_task_index];
          std::vector<int> reduced_left_route = left_route;
          reduced_left_route.erase(reduced_left_route.begin() + static_cast<std::ptrdiff_t>(left_task_index));

          for (std::size_t right_task_index = 0; right_task_index < right_route.size(); ++right_task_index) {
            const int right_target = right_route[right_task_index];
            std::vector<int> reduced_right_route = right_route;
            reduced_right_route.erase(reduced_right_route.begin() + static_cast<std::ptrdiff_t>(right_task_index));

            const auto left_insertion = best_insertion_for_candidate(
                input,
                left_robot_id,
                reduced_left_route,
                right_target,
                state[left_robot_id].budget_m);
            if (!left_insertion.has_value()) {
              continue;
            }

            const auto right_insertion = best_insertion_for_candidate(
                input,
                right_robot_id,
                reduced_right_route,
                left_target,
                state[right_robot_id].budget_m);
            if (!right_insertion.has_value()) {
              continue;
            }

            std::vector<Metric> metrics_after;
            metrics_after.reserve(robot_ids.size());
            for (int robot_id : robot_ids) {
              if (robot_id == left_robot_id) {
                metrics_after.push_back(left_insertion->metrics);
              } else if (robot_id == right_robot_id) {
                metrics_after.push_back(right_insertion->metrics);
              } else {
                metrics_after.push_back(state[robot_id].metrics);
              }
            }

            const Score candidate_score = score_from_metrics(metrics_after);
            if (!score_better(candidate_score, best_score)) {
              continue;
            }

            best_score = candidate_score;
            best_move = SwapMove{
                left_robot_id,
                right_robot_id,
                left_insertion->route,
                right_insertion->route,
                left_insertion->metrics,
                right_insertion->metrics,
            };
          }
        }
      }
    }

    if (!best_move.has_value()) {
      break;
    }

    state[best_move->left_robot_id].route = best_move->left_route;
    state[best_move->left_robot_id].metrics = best_move->left_metrics;
    state[best_move->right_robot_id].route = best_move->right_route;
    state[best_move->right_robot_id].metrics = best_move->right_metrics;
    optimize_specific_routes(input, state, {best_move->left_robot_id, best_move->right_robot_id});
    improved = true;
  }

  return improved;
}

std::pair<std::vector<StateEntry>, std::set<int>> run_heuristic_search(
    const NativePlannerInput& input,
    const std::vector<int>& target_ids,
    ConstructionMode mode,
    const std::vector<int>& robot_ids) {
  std::vector<StateEntry> state = build_state(input);
  std::set<int> unassigned(target_ids.begin(), target_ids.end());

  std::vector<double> difficulty_by_target(static_cast<std::size_t>(input.target_count), 0.0);
  for (int target_id : target_ids) {
    difficulty_by_target[target_id] = singleton_target_difficulty(input, state, target_id).first;
  }

  assign_remaining_targets(input, state, unassigned, robot_ids, difficulty_by_target, mode);
  optimize_specific_routes(input, state, robot_ids);
  assign_remaining_targets(input, state, unassigned, robot_ids, difficulty_by_target, mode);
  optimize_specific_routes(input, state, robot_ids);

  for (int pass = 0; pass < input.max_improvement_passes; ++pass) {
    bool progress = false;

    if (repair_unassigned_by_relocation(input, state, unassigned, robot_ids, difficulty_by_target)) {
      progress = true;
    }

    if (assign_remaining_targets(input, state, unassigned, robot_ids, difficulty_by_target, mode)) {
      progress = true;
    }

    if (relocate_improve(input, state, robot_ids)) {
      progress = true;
    }

    if (swap_improve(input, state, robot_ids)) {
      progress = true;
    }

    if (!progress) {
      break;
    }
    optimize_specific_routes(input, state, robot_ids);
  }

  return {state, unassigned};
}

void validate_input(const NativePlannerInput& input, const NativePlannerOutput& output) {
  if (input.robot_count < 1) {
    throw std::runtime_error("robot_count must be at least 1");
  }
  if (input.target_count < 0) {
    throw std::runtime_error("target_count must not be negative");
  }
  if (input.max_improvement_passes < 0) {
    throw std::runtime_error("max_improvement_passes must not be negative");
  }
  if (input.budgets_m == nullptr || output.route_lengths == nullptr || output.unassigned_mask == nullptr) {
    throw std::runtime_error("received null required planner buffers");
  }
  if (input.target_count > 0) {
    if (output.routes_flat == nullptr) {
      throw std::runtime_error("routes_flat buffer is required when target_count > 0");
    }
    if (input.start_reachable == nullptr || input.start_distance_m == nullptr || input.start_time_s == nullptr ||
        input.home_reachable == nullptr || input.home_distance_m == nullptr || input.home_time_s == nullptr ||
        input.pair_reachable == nullptr || input.pair_distance_m == nullptr || input.pair_time_s == nullptr) {
      throw std::runtime_error("received null cost buffers");
    }
  }
}

}  // namespace

extern "C" {

int solve_multi_robot_routes(const NativePlannerInput* input_ptr, NativePlannerOutput* output_ptr) {
  try {
    if (input_ptr == nullptr || output_ptr == nullptr) {
      throw std::runtime_error("planner input/output pointers must not be null");
    }

    const NativePlannerInput& input = *input_ptr;
    NativePlannerOutput& output = *output_ptr;
    validate_input(input, output);
    g_last_error.clear();

    const std::vector<int> default_robot_ids = [&input]() {
      std::vector<int> ids;
      ids.reserve(static_cast<std::size_t>(input.robot_count));
      for (int robot_id = 0; robot_id < input.robot_count; ++robot_id) {
        ids.push_back(robot_id);
      }
      return ids;
    }();

    std::vector<int> reversed_robot_ids = default_robot_ids;
    std::reverse(reversed_robot_ids.begin(), reversed_robot_ids.end());

    std::vector<int> target_ids;
    target_ids.reserve(static_cast<std::size_t>(input.target_count));
    for (int target_id = 0; target_id < input.target_count; ++target_id) {
      target_ids.push_back(target_id);
    }

    std::optional<std::vector<StateEntry>> best_state;
    std::optional<std::set<int>> best_unassigned;
    int best_assigned_count = -1;
    std::optional<Score> best_score;

    const std::vector<ConstructionMode> modes = {
        ConstructionMode::kRegret,
        ConstructionMode::kConstrained,
        ConstructionMode::kBestGlobal,
    };

    const std::vector<int>* robot_variants[] = {&default_robot_ids, &reversed_robot_ids};

    for (ConstructionMode mode : modes) {
      for (const std::vector<int>* robot_ids : robot_variants) {
        const auto [candidate_state, candidate_unassigned] =
            run_heuristic_search(input, target_ids, mode, *robot_ids);
        const int candidate_assigned_count =
            static_cast<int>(target_ids.size()) - static_cast<int>(candidate_unassigned.size());
        const Score candidate_score = state_score(candidate_state, default_robot_ids);

        if (final_solution_better(
                candidate_assigned_count,
                candidate_score,
                best_assigned_count,
                best_score)) {
          best_state = candidate_state;
          best_unassigned = candidate_unassigned;
          best_assigned_count = candidate_assigned_count;
          best_score = candidate_score;
        }
      }
    }

    if (!best_state.has_value() || !best_unassigned.has_value()) {
      best_state = build_state(input);
      best_unassigned = std::set<int>(target_ids.begin(), target_ids.end());
    }

    if (input.target_count > 0) {
      std::fill(output.routes_flat, output.routes_flat + input.robot_count * input.target_count, -1);
    }
    std::fill(output.unassigned_mask, output.unassigned_mask + input.target_count, 0);

    for (int robot_id = 0; robot_id < input.robot_count; ++robot_id) {
      const std::vector<int>& route = (*best_state)[robot_id].route;
      output.route_lengths[robot_id] = static_cast<int32_t>(route.size());
      for (std::size_t route_index = 0; route_index < route.size(); ++route_index) {
        output.routes_flat[robot_id * input.target_count + static_cast<int>(route_index)] = route[route_index];
      }
    }

    for (int target_id : *best_unassigned) {
      output.unassigned_mask[target_id] = 1;
    }

    return 0;
  } catch (const std::exception& exc) {
    g_last_error = exc.what();
    return 1;
  } catch (...) {
    g_last_error = "unknown native planner error";
    return 1;
  }
}

const char* planner_last_error() {
  if (g_last_error.empty()) {
    return kNoError;
  }
  return g_last_error.c_str();
}

}  // extern "C"
