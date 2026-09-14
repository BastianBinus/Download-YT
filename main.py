import yt_dlp

url = input("Youtube URL: ")

ydl_opts = {
    "format": "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/best[vcodec^=avc1]/best",
    "merge_output_format": "mp4",
}

yt_dlp.YoutubeDL(ydl_opts).download([url])