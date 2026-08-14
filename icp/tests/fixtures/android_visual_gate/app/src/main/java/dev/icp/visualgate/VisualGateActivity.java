package dev.icp.visualgate;

import android.app.Activity;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.TextView;

abstract class VisualGateActivity extends Activity {
    private static int dp(Activity activity, int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    protected abstract boolean hasDefects();

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        getWindow().setFlags(
            WindowManager.LayoutParams.FLAG_FULLSCREEN,
            WindowManager.LayoutParams.FLAG_FULLSCREEN
        );

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.WHITE);
        root.setContentDescription("icp:root");
        setContentView(root);

        TextView heading = new TextView(this);
        heading.setText("Verified Android visual gate");
        heading.setTextSize(22);
        heading.setTextColor(Color.rgb(32, 33, 36));
        heading.setGravity(Gravity.CENTER_VERTICAL);
        heading.setContentDescription("icp:heading");
        add(root, heading, 20, 24, 330, 48);

        TextView action = new TextView(this);
        action.setText("Continue");
        action.setTextSize(18);
        action.setTextColor(Color.WHITE);
        action.setGravity(Gravity.CENTER);
        action.setBackgroundColor(Color.rgb(0, 121, 107));
        action.setContentDescription("icp:action");
        add(root, action, 20, hasDefects() ? 110 : 100, 160, 48);

        View icon;
        if (hasDefects()) {
            ImageView materialSymbol = new ImageView(this);
            materialSymbol.setImageResource(R.drawable.material_symbols_close);
            materialSymbol.setScaleType(ImageView.ScaleType.CENTER);
            icon = materialSymbol;
        } else {
            icon = new ApprovedAssetView(this);
        }
        icon.setBackgroundColor(Color.rgb(232, 245, 233));
        icon.setContentDescription("icp:action-icon");
        add(root, icon, 20, 200, 48, 48);
    }

    private void add(
        FrameLayout parent,
        View child,
        int left,
        int top,
        int width,
        int height
    ) {
        FrameLayout.LayoutParams params = new FrameLayout.LayoutParams(dp(this, width), dp(this, height));
        params.leftMargin = dp(this, left);
        params.topMargin = dp(this, top);
        parent.addView(child, params);
    }

    private static final class ApprovedAssetView extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        ApprovedAssetView(Activity activity) {
            super(activity);
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float scale = getWidth() / 48.0f;
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(Color.rgb(0, 137, 123));
            canvas.drawCircle(24 * scale, 24 * scale, 18 * scale, paint);

            paint.setStyle(Paint.Style.STROKE);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
            paint.setStrokeWidth(4 * scale);
            paint.setColor(Color.WHITE);
            Path check = new Path();
            check.moveTo(14 * scale, 24 * scale);
            check.lineTo(21 * scale, 31 * scale);
            check.lineTo(35 * scale, 16 * scale);
            canvas.drawPath(check, paint);
        }
    }
}
