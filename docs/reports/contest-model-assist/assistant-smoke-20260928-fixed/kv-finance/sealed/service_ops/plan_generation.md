# Public request plan generation
Seed=20260924. For W07/W08 independently: rng=random.Random(f'{seed}:service_request_plan:{period}'); for S-A,S-B,S-C,S-D in that order (zero-based index), planned_request_count=12000+250*index+rng.randrange(0,600). Plans are frozen before execution and independent of actual results/model output.
