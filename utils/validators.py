import magic
from fastapi import UploadFile, HTTPException

# Defining Allowed Upload Video Types
# MP4 = video/mp4
# WebM = video/webm
ALLOWED_MIME_TYPES = ["video/mp4", "video/webm"] # List that is valid

async def validate_video_file_signature(file: UploadFile):
    """
    Validates the file format using Magic Bytes (File Signature).
    Does NOT rely on the file extension.
    
    Args:
        file (UploadFile): The file object uploaded by the user.
        
    Raises:
        HTTPException: If the file format is not allowed.
    """
    
    # 1. Read the first 2048 bytes (Header) of the file
    # We don't need to read the whole file (which could be 1GB) just to check the type.
    header_bytes = await file.read(2048)
    
    # 2. Use python-magic to detect the REAL MIME type from the bytes
    mime_type = magic.from_buffer(header_bytes, mime=True)
    
    # 3. Log the detected type for debugging purposes
    print(f"🔍 Security Check: Detected MIME Type: {mime_type}")
    
    # 4. Reset the file cursor position to the beginning!
    # CRITICAL: If we don't do this, when we try to save the file later,
    # it will start saving from byte 2048, resulting in a corrupted video.
    await file.seek(0)
    
    # 5. Check against allowed types
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {mime_type}. Only MP4 and WebM are allowed."
        )
    
    return True