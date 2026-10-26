use pyo3::prelude::*;
use std::collections::HashMap;

/// Find the same longest contiguous matching block used by
/// difflib.SequenceMatcher(autojunk=False), with no junk predicate.
///
/// Iterating i and then sorted positions in b preserves SequenceMatcher's
/// earliest-i, earliest-j tie break. The caller's strings are Unicode scalar
/// sequences, which match Python str indexing for ordinary valid Unicode.
fn longest_matching_block(
    a: &[char],
    alo: usize,
    ahi: usize,
    b: &[char],
    blo: usize,
    bhi: usize,
    b_positions: &HashMap<char, Vec<usize>>,
) -> (usize, usize, usize) {
    let (mut best_i, mut best_j, mut best_size) = (alo, blo, 0usize);
    let mut previous_lengths: HashMap<usize, usize> = HashMap::new();

    for i in alo..ahi {
        let mut current_lengths: HashMap<usize, usize> = HashMap::new();

        if let Some(positions) = b_positions.get(&a[i]) {
            for &j in positions {
                if j < blo {
                    continue;
                }
                if j >= bhi {
                    break;
                }

                let size = j
                    .checked_sub(1)
                    .and_then(|previous_j| previous_lengths.get(&previous_j).copied())
                    .unwrap_or(0)
                    + 1;
                current_lengths.insert(j, size);

                // Strict comparison is deliberate: ties keep the first match,
                // exactly like difflib.SequenceMatcher.find_longest_match.
                if size > best_size {
                    best_i = i + 1 - size;
                    best_j = j + 1 - size;
                    best_size = size;
                }
            }
        }
        previous_lengths = current_lengths;
    }

    // With no junk predicate, these extensions include all immediately
    // adjacent equal characters at either end of the best contiguous block.
    while best_i > alo && best_j > blo && a[best_i - 1] == b[best_j - 1] {
        best_i -= 1;
        best_j -= 1;
        best_size += 1;
    }
    while best_i + best_size < ahi
        && best_j + best_size < bhi
        && a[best_i + best_size] == b[best_j + best_size]
    {
        best_size += 1;
    }

    (best_i, best_j, best_size)
}

/// Compute difflib.SequenceMatcher(None, left, right, autojunk=False).ratio().
///
/// Only the matching-block algorithm runs in Rust; title normalization and the
/// app's exact/containment checks remain in Python. Matching semantics are kept
/// compatible so provider-match ranking does not change.
fn sequence_match_ratio_impl(a: &[char], b: &[char]) -> f64 {
    let total_length = a.len() + b.len();
    if total_length == 0 {
        // difflib returns 1.0 when both sequences are empty.
        return 1.0;
    }

    let mut b_positions: HashMap<char, Vec<usize>> = HashMap::new();
    for (j, character) in b.iter().copied().enumerate() {
        b_positions.entry(character).or_default().push(j);
    }

    // SequenceMatcher recursively finds matching blocks to the left and right
    // of the best block. Their order does not affect the sum of matched lengths.
    let mut pending = vec![(0usize, a.len(), 0usize, b.len())];
    let mut matched_characters = 0usize;

    while let Some((alo, ahi, blo, bhi)) = pending.pop() {
        let (i, j, size) =
            longest_matching_block(a, alo, ahi, b, blo, bhi, &b_positions);
        if size == 0 {
            continue;
        }

        matched_characters += size;
        if alo < i && blo < j {
            pending.push((alo, i, blo, j));
        }
        if i + size < ahi && j + size < bhi {
            pending.push((i + size, ahi, j + size, bhi));
        }
    }

    (2.0 * matched_characters as f64) / total_length as f64
}

#[pyfunction]
fn sequence_match_ratio(py: Python<'_>, left: String, right: String) -> f64 {
    // Own the strings before detaching, then release the GIL while the native
    // matching loop runs. No Python objects are touched by the detached closure.
    let left: Vec<char> = left.chars().collect();
    let right: Vec<char> = right.chars().collect();
    py.detach(move || sequence_match_ratio_impl(&left, &right))
}

#[pymodule]
fn _nekotrack_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(sequence_match_ratio, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::sequence_match_ratio_impl;

    #[test]
    fn handles_empty_and_identical_sequences() {
        assert_eq!(sequence_match_ratio_impl(&[], &[]), 1.0);
        assert_eq!(sequence_match_ratio_impl(&[], &['a']), 0.0);
        assert_eq!(
            sequence_match_ratio_impl(&['n', 'e', 'k', 'o'], &['n', 'e', 'k', 'o']),
            1.0
        );
    }

    #[test]
    fn preserves_leftmost_matching_block_tie_break() {
        let a: Vec<char> = "ab".chars().collect();
        let b: Vec<char> = "ba".chars().collect();
        assert_eq!(sequence_match_ratio_impl(&a, &b), 0.5);
    }
}
