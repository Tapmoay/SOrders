# Retrofit / kotlinx.serialization
-keepattributes Signature, InnerClasses, EnclosingMethod, *Annotation*
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keep,includedescriptorclasses class com.tapmoay.sorders.**$$serializer { *; }
-keepclassmembers class com.tapmoay.sorders.** { *** Companion; }
-dontwarn okhttp3.**
-dontwarn okio.**
# 高德
-keep class com.amap.api.** { *; }
-keep class com.loc.** { *; }
-dontwarn com.amap.api.**
