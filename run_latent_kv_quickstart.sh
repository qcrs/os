#!/bin/bash
# Quick start guide for latent_kv D mode

echo "========================================="
echo "Latent KV D Mode - Quick Start"
echo "========================================="
echo ""

# Check environment
echo "1. Checking environment..."
if command -v docker &> /dev/null && docker ps | grep -q SynapseX-wmw71; then
    echo "  ✓ Docker container SynapseX-wmw71 is running"
    DOCKER_AVAILABLE=1
else
    echo "  ⚠ Docker container not available (simulation mode only)"
    DOCKER_AVAILABLE=0
fi

echo ""
echo "2. Setting up environment variables..."
export PYTHONPATH="$(pwd)/src:$PYTHONPATH"
export COMM_MODE=latent_kv
export ANALYST_LATENT_STEPS=64
export EXECUTOR_LATENT_STEPS=32
export POST_EXEC_LATENT_STEPS=16
export LATENT_ALIGNMENT=normalized_identity

echo "  ✓ PYTHONPATH set"
echo "  ✓ Configuration set:"
echo "    - ANALYST_LATENT_STEPS: $ANALYST_LATENT_STEPS"
echo "    - EXECUTOR_LATENT_STEPS: $EXECUTOR_LATENT_STEPS"
echo "    - POST_EXEC_LATENT_STEPS: $POST_EXEC_LATENT_STEPS"

echo ""
echo "3. Running standalone tests (no dependencies)..."
python3 exp/latent_kv_exp/test_latent_kv_runtime.py
TEST_STATUS=$?

if [ $TEST_STATUS -eq 0 ]; then
    echo ""
    echo "========================================="
    echo "✅ Latent KV D Mode is Ready"
    echo "========================================="
    echo ""
    echo "Next steps:"
    echo ""
    echo "1. Run demo (requires langgraph):"
    echo "   python3 exp/latent_kv_exp/run_latent_kv_demo.py"
    echo ""
    echo "2. Run A/B/C/D comparison:"
    echo "   python3 exp/latent_kv_exp/run_abcd_comparison.py"
    echo ""
    echo "3. Read documentation:"
    echo "   cat exp/latent_kv_exp/README.md"
    echo "   cat LATENT_KV_IMPLEMENTATION.md"
    echo ""
else
    echo ""
    echo "❌ Tests failed. Please check the error messages above."
    exit 1
fi
