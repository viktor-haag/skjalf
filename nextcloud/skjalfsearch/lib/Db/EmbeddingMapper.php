<?php

declare(strict_types=1);

/**
 * @copyright Copyright (c) 2024 Skjalf Team
 *
 * @author Skjalf Team
 *
 * @license AGPL-3.0-or-later
 */

namespace OCA\Skjalfsearch\Db;

use OCP\AppFramework\Db\DoesNotExistException;
use OCP\AppFramework\Db\MultipleObjectsReturnedException;
use OCP\AppFramework\Db\QBMapper;
use OCP\DB\QueryBuilder\IQueryBuilder;
use OCP\IDBConnection;

/**
 * Database mapper for embedding status records.
 *
 * Tracks which Nextcloud files have been embedded, their embedding progress,
 * and the ChromaDB document ID for reference.
 */
class EmbeddingMapper extends QBMapper {
	private const TABLE = 'skjalf_embeddings';

	public function __construct(IDBConnection $db) {
		parent::__construct($db, self::TABLE);
	}

	/**
	 * Get embedding status for a file.
	 *
	 * @param int $fileId Nextcloud file ID
	 * @return EmbeddingRecord
	 * @throws DoesNotExistException
	 */
	public function findByFileId(int $fileId): EmbeddingRecord {
		$qb = $this->db->getQueryBuilder();
		$qb->select('*')
			->from(self::TABLE)
			->where($qb->eq('file_id', $qb->createNamedParameter($fileId, IQueryBuilder::PARAM_INT)));

		return $qb->executeQuery()->fetch();
	}

	/**
	 * Save or update embedding status.
	 *
	 * @param int $fileId Nextcloud file ID
	 * @param string $status One of: pending, processing, complete, error
	 * @param string|null $chromaId ChromaDB document ID
	 * @param int $progress Progress percentage (0-100)
	 * @param string|null $error Error message if status is 'error'
	 */
	public function saveStatus(
		int $fileId,
		string $status = 'pending',
		?string $chromaId = null,
		int $progress = 0,
		?string $error = null,
	): void {
		$qb = $this->db->getQueryBuilder();

		// Check if record exists
		$existing = null;
		try {
			$existing = $this->findByFileId($fileId);
		} catch (DoesNotExistException) {
			// Will create new record
		}

		if ($existing !== null) {
			// Update existing record
			$existing->setStatus($status);
			$existing->setChromaId($chromaId);
			$existing->setProgress($progress);
			$existing->setError($error);
			$this->update($existing);
		} else {
			// Create new record
			$record = new EmbeddingRecord();
			$record->setFileId($fileId);
			$record->setStatus($status);
			$record->setChromaId($chromaId);
			$record->setProgress($progress);
			$record->setError($error);
			$this->insert($record);
		}
	}

	/**
	 * Find all files that need embedding (pending or error).
	 *
	 * @return EmbeddingRecord[]
	 */
	public function findPending(): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('*')
			->from(self::TABLE)
			->where(
				$qb->eq('status', $qb->createNamedParameter('pending')),
				$qb->eq('status', $qb->createNamedParameter('error'), IQueryBuilder::PARAM_OR),
			)
			->orderBy('created_at', 'asc');

		return $qb->executeQuery()->fetchAll();
	}

	/**
	 * Find all embedded files for a given folder.
	 *
	 * @param string $folderPath Folder path
	 * @return array List of file IDs
	 */
	public function findFilesInFolder(string $folderPath): array {
		$qb = $this->db->getQueryBuilder();
		$qb->select('file_id')
			->from(self::TABLE)
			->where(
				$qb->like('file_path', $qb->createNamedParameter($folderPath . '%')),
				$qb->eq('status', $qb->createNamedParameter('complete')),
			);

		$records = $qb->executeQuery()->fetchAll();
		return array_map(fn ($r) => (int) $r['file_id'], $records);
	}

	/**
	 * Delete embedding records for files that no longer exist.
	 *
	 * This is a cleanup method called by the background job.
	 */
	public function cleanupOrphaned(): int {
		$qb = $this->db->getQueryBuilder();
		$allRecords = $qb->select('*')->from(self::TABLE)->executeQuery()->fetchAll();

		$deleted = 0;
		foreach ($allRecords as $record) {
			// Check if file still exists in the filesystem
			$fileExists = $this->fileExists((int) $record['file_id']);
			if (!$fileExists) {
				// Delete the record
				$deleteQb = $this->db->getQueryBuilder();
				$deleteQb->delete(self::TABLE)
					->where($deleteQb->eq('file_id', $deleteQb->createNamedParameter($record['file_id'], IQueryBuilder::PARAM_INT)));
				$deleteQb->executeStatement();
				$deleted++;
			}
		}

		return $deleted;
	}

	/**
	 * Check if a file still exists in the Nextcloud filesystem.
	 */
	private function fileExists(int $fileId): bool {
		try {
			$root = \OC\Files\Filesystem::getRoot();
			$nodes = $root->getById($fileId);
			return !empty($nodes);
		} catch (\Exception) {
			return false;
		}
	}
}
