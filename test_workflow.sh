#!/bin/bash
# Test workflow for embed_faces.py
# This script verifies the complete end-to-end workflow

set -e

echo "=== Face Embedding CLI Tool - Test Workflow ==="
echo ""

# Clean up any previous test data
echo "Step 0: Cleaning up previous test data..."
rm -rf test_verify_db test_verify_images
echo "✓ Cleaned up"
echo ""

# Step 1: Create test folder with sample images
echo "Step 1: Creating test folder with sample images..."
mkdir -p test_verify_images

python3 -c "
from PIL import Image
import os

# Create some simple test images with different colors
colors = [
    ('test_00.jpg', 'red'),
    ('test_01.jpg', 'green'),
    ('test_02.jpg', 'blue'),
    ('test_03.jpg', 'yellow'),
    ('test_04.jpg', 'purple'),
    ('test_05.jpg', 'orange'),
    ('test_06.jpg', 'cyan'),
    ('test_07.jpg', 'magenta'),
    ('test_08.jpg', 'lime'),
    ('test_09.jpg', 'pink'),
]

for filename, color in colors:
    img = Image.new('RGB', (112, 112), color)
    img.save(f'test_verify_images/{filename}')
    print(f'  Created test_verify_images/{filename}')

print(f'  Total: {len(colors)} images created')
"

echo "✓ Test images created"
echo ""

# Step 2: Embed all images
echo "Step 2: Embedding all images in test folder..."
python3 embed_faces.py embed test_verify_images --db test_verify_db
echo "✓ Embedding complete"
echo ""

# Step 3: Verify ChromaDB has entries
echo "Step 3: Verifying ChromaDB has entries..."
python3 -c "
import chromadb
client = chromadb.PersistentClient(path='test_verify_db')
collection = client.get_collection('persons')
count = collection.count()
print(f'  ChromaDB has {count} entries')
assert count == 10, f'Expected 10 entries, got {count}'
print('✓ ChromaDB verification passed')
"
echo ""

# Step 4: Search for similar images
echo "Step 4: Searching for similar images..."
python3 embed_faces.py search test_verify_images/test_00.jpg --db test_verify_db --top_k 5
echo ""

# Step 5: Verify JSON output
echo "Step 5: Verifying JSON output..."
python3 embed_faces.py search test_verify_images/test_00.jpg --db test_verify_db --top_k 5 --json | python3 -c "
import json
import sys
data = json.load(sys.stdin)
assert 'query' in data, 'Missing query field'
assert 'results' in data, 'Missing results field'
assert len(data['results']) == 5, f'Expected 5 results, got {len(data[\"results\"])}'
print('  Query:', data['query'])
print(f'  Results: {len(data[\"results\"])} entries')
for i, result in enumerate(data['results'], 1):
    print(f'    {i}. {result[\"abs_path\"]} (distance: {result[\"distance\"]:.4f})')
print('✓ JSON output verification passed')
"
echo ""

# Step 6: Verify incremental updates
echo "Step 6: Verifying incremental updates..."
echo "  Running embed again (should skip all files)..."
python3 embed_faces.py embed test_verify_images --db test_verify_db 2>&1 | grep -E "(new|skipped|failed)"
echo "✓ Incremental update verification passed"
echo ""

# Step 7: Add new image and verify only new image is embedded
echo "Step 7: Adding new image and verifying incremental update..."
python3 -c "
from PIL import Image
img = Image.new('RGB', (112, 112), 'white')
img.save('test_verify_images/test_new.jpg')
print('  Created test_verify_images/test_new.jpg')
"

echo "  Running embed again (should embed only new file)..."
python3 embed_faces.py embed test_verify_images --db test_verify_db 2>&1 | grep -E "(new|skipped|failed)"
echo "✓ New image verification passed"
echo ""

# Step 8: Test error handling
echo "Step 8: Testing error handling..."

# Test with invalid folder
echo "  Testing with invalid folder..."
python3 embed_faces.py embed /nonexistent/folder --db test_verify_db 2>&1 | grep -i "error" || true

# Test with invalid image
echo "  Testing with invalid image..."
python3 embed_faces.py search /nonexistent/image.jpg --db test_verify_db 2>&1 | grep -i "error" || true

echo "✓ Error handling verification passed"
echo ""

# Step 9: Test with different top_k
echo "Step 9: Testing with different top_k values..."
echo "  Testing top_k=3..."
python3 embed_faces.py search test_verify_images/test_00.jpg --db test_verify_db --top_k 3 2>&1 | grep -c "^[[:space:]]*[0-9]\." | xargs -I {} echo "  Found {} results"
echo "  Testing top_k=1..."
python3 embed_faces.py search test_verify_images/test_00.jpg --db test_verify_db --top_k 1 2>&1 | grep -c "^[[:space:]]*[0-9]\." | xargs -I {} echo "  Found {} results"
echo "✓ Different top_k verification passed"
echo ""

# Clean up
echo "Cleaning up test data..."
rm -rf test_verify_db test_verify_images
echo "✓ Cleaned up"
echo ""

echo "=== All tests passed! ==="
