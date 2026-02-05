# Google Cloud Run Deployment Guide

## 🚀 Deploy ไปยัง Google Cloud Run

### ขั้นตอนที่ 1: ติดตั้ง Google Cloud CLI
```bash
# สำหรับ macOS
brew install google-cloud-sdk

# หรือดาวน์โหลดจาก: https://cloud.google.com/sdk/docs/install
```

### ขั้นตอนที่ 2: Login และตั้งค่า
```bash
# Login เข้า Google Cloud
gcloud auth login

# ตั้งค่า project
gcloud config set project water-meter-ocr-483703

# Enable APIs ที่จำเป็น
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable containerregistry.googleapis.com
```

### ขั้นตอนที่ 3: Deploy
```bash
# รันสคริปต์ deploy
./deploy-cloudrun.sh
```

หรือ deploy แบบ manual:

```bash
# 1. Build Docker image
gcloud builds submit --tag gcr.io/water-meter-ocr-483703/water-meter-app .

# 2. Deploy to Cloud Run
gcloud run deploy water-meter-app \
  --image gcr.io/water-meter-ocr-483703/water-meter-app \
  --platform managed \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 3600
```

### ขั้นตอนที่ 4: ตั้งค่า Secrets (สำคัญ!)

Cloud Run ไม่มี `.streamlit/secrets.toml` ต้องใช้วิธีอื่น:

**Option 1: ใช้ Environment Variables**
```bash
# แปลง service_account.json เป็น base64
base64 service_account.json > sa_base64.txt

# Set env var
gcloud run services update water-meter-app \
  --region asia-southeast1 \
  --set-env-vars GCP_SERVICE_ACCOUNT_BASE64="$(cat sa_base64.txt)"
```

**Option 2: ใช้ Google Secret Manager (แนะนำ)**
```bash
# Enable Secret Manager API
gcloud services enable secretmanager.googleapis.com

# สร้าง secret
gcloud secrets create gcp-service-account \
  --data-file=service_account.json

# ให้ Cloud Run access secret
gcloud run services update water-meter-app \
  --region asia-southeast1 \
  --set-secrets=/secrets/gcp-service-account.json=gcp-service-account:latest
```

### เช็คสถานะ
```bash
# ดู URL ของ app
gcloud run services describe water-meter-app \
  --region asia-southeast1 \
  --format 'value(status.url)'

# ดู logs
gcloud run services logs read water-meter-app --region asia-southeast1
```

### Update app (deploy version ใหม่)
```bash
./deploy-cloudrun.sh
```

### ลบ service
```bash
gcloud run services delete water-meter-app --region asia-southeast1
```

## 💰 ค่าใช้จ่าย

Cloud Run คิดค่าใช้จ่ายตามการใช้งานจริง:
- **Memory**: 2GB = ~$0.0025 ต่อ GB-second
- **CPU**: 2 vCPU = ~$0.024 ต่อ vCPU-second
- **Requests**: $0.40 ต่อล้าน requests

**Free tier**: 2 million requests/month ฟรี

## 🔧 Troubleshooting

### 1. ถ้า build ล่าช้า
```bash
# ใช้ local Docker build แทน
docker build -t gcr.io/water-meter-ocr-483703/water-meter-app .
docker push gcr.io/water-meter-ocr-483703/water-meter-app
```

### 2. ถ้าเจอ memory error
```bash
# เพิ่ม memory
gcloud run services update water-meter-app \
  --memory 4Gi \
  --region asia-southeast1
```

### 3. ถ้าเจอ timeout
```bash
# เพิ่ม timeout (max 3600 วินาที = 1 ชั่วโมง)
gcloud run services update water-meter-app \
  --timeout 3600 \
  --region asia-southeast1
```

### 4. ถ้าไม่มี gcloud command
```bash
# ติดตั้ง Google Cloud SDK
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
gcloud init
```

## 📱 หลังจาก Deploy แล้ว

1. เปิดเว็บที่ URL ที่ได้
2. ทดสอบ OCR ด้วยรูปตัวอย่าง
3. ตั้งค่า Custom Domain (ถ้าต้องการ)
4. ตั้งค่า HTTPS และ Authentication (ถ้าต้องการ)
