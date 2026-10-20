import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import {
  computeStepPercent,
  computeOverallProgress,
  computeEta,
  createInitialBatchProgressState,
  batchProgressReducer,
} from './progressReducer.ts';

describe('1. Percent Math', () => {
  test('computes exact percentage from done and total', () => {
    const res = computeStepPercent(7, 12, 'running');
    assert.strictEqual(res.percent, 58);
    assert.strictEqual(res.isIndeterminate, false);
  });

  test('computes 10 of 14 as 71%', () => {
    const res = computeStepPercent(10, 14, 'running');
    assert.strictEqual(res.percent, 71);
    assert.strictEqual(res.isIndeterminate, false);
  });

  test('computes 13 of 42 as 31%', () => {
    const res = computeStepPercent(13, 42, 'running');
    assert.strictEqual(res.percent, 31);
    assert.strictEqual(res.isIndeterminate, false);
  });

  test('clamps percent between 0 and 100', () => {
    const resOver = computeStepPercent(150, 100, 'running');
    assert.strictEqual(resOver.percent, 100);

    const resUnder = computeStepPercent(-5, 100, 'running');
    assert.strictEqual(resUnder.percent, 0);
  });

  test('status done always returns 100%', () => {
    const res = computeStepPercent(3, 3, 'done');
    assert.strictEqual(res.percent, 100);
    assert.strictEqual(res.isIndeterminate, false);
  });
});

describe('2. Indeterminate Handling', () => {
  test('returns null percent and isIndeterminate=true when total is null and status is running', () => {
    const res = computeStepPercent(5, null, 'running');
    assert.strictEqual(res.percent, null);
    assert.strictEqual(res.isIndeterminate, true);
  });

  test('returns null percent and isIndeterminate=true when total is 0 and status is running', () => {
    const res = computeStepPercent(0, 0, 'running');
    assert.strictEqual(res.percent, null);
    assert.strictEqual(res.isIndeterminate, true);
  });

  test('returns null percent and isIndeterminate=false when status is waiting', () => {
    const res = computeStepPercent(0, null, 'waiting');
    assert.strictEqual(res.percent, null);
    assert.strictEqual(res.isIndeterminate, false);
  });
});

describe('3. Overall Average Progress', () => {
  test('overall progress is indeterminate when no steps have known totals', () => {
    const state = createInitialBatchProgressState('test-b1');
    const { overallPercent, isOverallIndeterminate } = computeOverallProgress(state.steps);
    assert.strictEqual(overallPercent, null);
    assert.strictEqual(isOverallIndeterminate, true);
  });

  test('computes mean of known step percentages excluding indeterminate steps', () => {
    const state = createInitialBatchProgressState('test-b1');

    // Step 1: Ingest 3 of 3 (100%)
    state.steps.ingest.status = 'done';
    state.steps.ingest.done = 3;
    state.steps.ingest.total = 3;
    state.steps.ingest.percent = 100;

    // Step 2: Parse 10 of 14 (71%)
    state.steps.parse.status = 'running';
    state.steps.parse.done = 10;
    state.steps.parse.total = 14;
    state.steps.parse.percent = 71;

    // Step 3: Map 13 of 42 (31%)
    state.steps.map.status = 'running';
    state.steps.map.done = 13;
    state.steps.map.total = 42;
    state.steps.map.percent = 31;

    // Steps 4, 5, 6: total null (waiting) -> excluded
    const { overallPercent, isOverallIndeterminate } = computeOverallProgress(state.steps);
    // Mean of (100 + 71.428 + 30.952) / 3 = 202.38 / 3 = 67%
    assert.strictEqual(overallPercent, 67);
    assert.strictEqual(isOverallIndeterminate, false);
  });

  test('when all steps are done, overall progress is 100%', () => {
    const state = createInitialBatchProgressState('test-b1');
    for (const key of Object.keys(state.steps)) {
      state.steps[key].status = 'done';
      state.steps[key].percent = 100;
    }
    const { overallPercent, isOverallIndeterminate } = computeOverallProgress(state.steps);
    assert.strictEqual(overallPercent, 100);
    assert.strictEqual(isOverallIndeterminate, false);
  });
});

describe('4. Out-of-Order Events & Monotonicity', () => {
  test('ignores events with older timestamp', () => {
    const state = createInitialBatchProgressState('test-b1');
    const now = 100000;

    // Progress at t = 100000 with done = 5
    const state1 = batchProgressReducer(state, {
      type: 'EVENT',
      event: {
        type: 'step_progress',
        batch_id: 'test-b1',
        step: 'parse',
        status: 'running',
        done: 5,
        total: 10,
        unit: 'pages',
        ts: now,
      },
    });

    assert.strictEqual(state1.steps.parse.done, 5);

    // Stale event at t = 90000 with done = 3
    const state2 = batchProgressReducer(state1, {
      type: 'EVENT',
      event: {
        type: 'step_progress',
        batch_id: 'test-b1',
        step: 'parse',
        status: 'running',
        done: 3,
        total: 10,
        unit: 'pages',
        ts: now - 10000,
      },
    });

    // Must NOT have moved backwards
    assert.strictEqual(state2.steps.parse.done, 5);
  });

  test('ignores lower done value when timestamps are equal', () => {
    const state = createInitialBatchProgressState('test-b1');
    const now = 100000;

    const state1 = batchProgressReducer(state, {
      type: 'EVENT',
      event: {
        type: 'step_progress',
        batch_id: 'test-b1',
        step: 'parse',
        status: 'running',
        done: 8,
        total: 10,
        unit: 'pages',
        ts: now,
      },
    });

    const state2 = batchProgressReducer(state1, {
      type: 'EVENT',
      event: {
        type: 'step_progress',
        batch_id: 'test-b1',
        step: 'parse',
        status: 'running',
        done: 4,
        total: 10,
        unit: 'pages',
        ts: now + 1,
      },
    });

    assert.strictEqual(state2.steps.parse.done, 8);
  });
});

describe('5. Step Restart Reset', () => {
  test('resets step done when status returns to running with a new run_id', () => {
    const state = createInitialBatchProgressState('test-b1');
    const now = 100000;

    // Initial run reaches done = 10
    const state1 = batchProgressReducer(state, {
      type: 'EVENT',
      event: {
        type: 'step_progress',
        batch_id: 'test-b1',
        step: 'parse',
        status: 'running',
        done: 10,
        total: 14,
        unit: 'pages',
        run_id: 'run-1',
        ts: now,
      },
    });
    assert.strictEqual(state1.steps.parse.done, 10);

    // Restart with new run_id 'run-2' and done = 0
    const state2 = batchProgressReducer(state1, {
      type: 'EVENT',
      event: {
        type: 'step_progress',
        batch_id: 'test-b1',
        step: 'parse',
        status: 'running',
        done: 0,
        total: 14,
        unit: 'pages',
        run_id: 'run-2',
        ts: now + 5000,
      },
    });

    // Reset should succeed because run_id changed
    assert.strictEqual(state2.steps.parse.done, 0);
    assert.strictEqual(state2.steps.parse.runId, 'run-2');
  });
});

describe('6. ETA Calculation', () => {
  test('returns null when less than 3 samples', () => {
    const samples = [
      { ts: 1000, percent: 10 },
      { ts: 2000, percent: 20 },
    ];
    assert.strictEqual(computeEta(samples, 20), null);
  });

  test('computes ETA accurately with >= 3 samples of throughput', () => {
    const samples = [
      { ts: 1000, percent: 10 },
      { ts: 6000, percent: 30 },
      { ts: 11000, percent: 50 },
    ];
    // 40% in 10s = 4% per second
    // Remaining: 50% / 4% = 12.5s -> 13s
    const eta = computeEta(samples, 50);
    assert.strictEqual(eta, 13);
  });
});
