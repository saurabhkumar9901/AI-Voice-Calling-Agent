'use client';

import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { client } from '@/client';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import logger from '@/lib/logger';

interface CsvUploadSelectorProps {
  accessToken: string;
  onFileUploaded: (fileKey: string, fileName: string) => void;
  selectedFileName?: string;
}

interface PresignedUploadUrlResponse {
  upload_url: string;
  file_key: string;
  expires_in: number;
}

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

export default function CsvUploadSelector({ accessToken, onFileUploaded, selectedFileName }: CsvUploadSelectorProps) {
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.name.endsWith('.csv')) {
      toast.error('Please select a CSV file');
      return;
    }

    // Validate file size
    if (file.size > MAX_FILE_SIZE) {
      toast.error('File size must be less than 10MB');
      return;
    }

    setUploading(true);
    setUploadProgress(0);

    try {
      // We bypass the Next.js proxy by using the direct backend URL from the client config
      // to avoid Next.js rewrite bugs with multipart/form-data that cause 403/400 errors.
      const formData = new FormData();
      formData.append('file', file);

      const baseUrl = client.getConfig().baseUrl || '';
      const uploadUrl = `${baseUrl}/api/v1/s3/upload-csv-direct`;

      const response = await fetch(uploadUrl, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
        },
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(error.detail || 'Failed to upload CSV');
      }

      const data: PresignedUploadUrlResponse = await response.json();
      setUploadProgress(100);
      logger.info('CSV uploaded successfully, file_key:', data.file_key);

      // Notify parent with file_key
      onFileUploaded(data.file_key, file.name);
      toast.success(`File uploaded: ${file.name}`);
    } catch (error) {
      logger.error('Error uploading CSV:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to upload CSV file');
    } finally {
      setUploading(false);
      setUploadProgress(0);
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className="space-y-2">
      <Label>CSV File</Label>
      <div className="flex items-center gap-4">
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv"
          onChange={handleFileSelect}
          className="hidden"
        />
        <Button
          type="button"
          variant="outline"
          onClick={handleButtonClick}
          disabled={uploading}
        >
          {uploading ? `Uploading... ${uploadProgress}%` : 'Upload CSV File'}
        </Button>
        {selectedFileName && !uploading && (
          <div className="flex-1 text-sm">
            <span className="text-muted-foreground">Selected: </span>
            <span className="text-primary">{selectedFileName}</span>
          </div>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        Upload a CSV file with contact data. Must include phone_number column.
        The columns can be accessed as initial_context in the workflow nodes. <br/>
        Max 10MB.
      </p>
    </div>
  );
}
