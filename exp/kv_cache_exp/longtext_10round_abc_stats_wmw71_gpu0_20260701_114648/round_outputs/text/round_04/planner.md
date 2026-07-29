[Round 4 / task 9004 full textual handoff]
Planner:
{
  "plan": "Implement storm, shield, and package damage systems. Add storm tile type with risk effects. Introduce shield field to PlayerState. Add package fragility to OrderState. Track damaged status. Define risk roll logic with deterministic seed. Ensure wind_lane and storm interaction. Add 8 test cases for storm effects, shield depletion, package damage, and risk roll outcomes.",
  "sub_queries": [
    "How to represent storm tile effects in LevelState?",
    "What data structures are needed for shield and package damage tracking?",
    "How to implement deterministic risk roll for testing?"
  ],
  "answer_tags": "@round[4] @feature_scope[storm_shield